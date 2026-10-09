"""Track memory orchestration: live track activation, lap association, profile statistics and
learned driving events.

Three kinds of data are kept apart:
  * static circuit metadata       track_metadata/   (read-only, see tracks/metadata.py)
  * learned track profiles        data/tracks/      (this service writes them)
  * lap -> track associations     data/laps/<id>.meta.json sidecars (lap_tracks.py)

Profile statistics (sessions, valid laps, personal best) are recomputed from the recorded lap
files every time, so reloading or repeating a call can never double count.
"""

import copy
import json
import threading
from pathlib import Path

from corner_analysis import detect_events
from lap_compare import CompareError, compare_laps, load_lap
from session_packet import UNKNOWN_TRACK_ID
from tracks.corners import map_point
from tracks.geometry import GeometryConfig, LapInput, axes_report, build_geometry, orientation, resample
from tracks.lap_tracks import SOURCE_MANUAL, SOURCE_TELEMETRY, LapTrack, LapTrackIndex, atomic_write_json
from tracks.learning import LearningConfig, ObservedEvent, update_learned_events
from tracks.metadata import MetadataRepository
from tracks.positions import PositionStore
from tracks.profiles import ProfileStore, new_profile, now_iso


class UnknownTrackError(ValueError):
    """A track ID that the application has no catalog or metadata entry for."""


class TrackConflictError(RuntimeError):
    """The requested change would override information the game itself reported."""


def format_lap_time(ms):
    if ms is None:
        return None
    minutes, rest = divmod(ms, 60000)
    return f"{minutes}:{rest / 1000:06.3f}"


class TrackService:
    def __init__(self, data_dir, metadata_dir=None, learning=None):
        data_dir = Path(data_dir)
        self.laps_dir = data_dir / "laps"
        self.profiles = ProfileStore(data_dir / "tracks")
        self.metadata = MetadataRepository(metadata_dir)
        self.lap_tracks = LapTrackIndex(self.laps_dir)
        self.positions = PositionStore(data_dir / "positions")  # per-lap world positions (Motion packets)
        self.maps_dir = data_dir / "track_maps"  # generated circuit traces
        self.geometry = GeometryConfig()
        self.learning = learning or LearningConfig()
        self._lock = threading.RLock()  # the recorder thread and API threads both call in

    # ------------------------------------------------------------------ identity

    def identify(self, track_id):
        entry = self.metadata.catalog().get(int(track_id))
        return {
            "track_id": int(track_id),
            "name": self.metadata.display_name(track_id),
            "circuit_name": entry.circuit_name if entry else None,
            "known": self.metadata.is_known(track_id),
        }

    def catalog(self):
        """Every circuit a lap can be assigned to, for the track picker."""
        return [self.identify(tid) | {"has_corner_metadata": self.metadata.get_track(tid) is not None}
                for tid in sorted(self.metadata.catalog())]

    def corner_metadata(self, track_id):
        return self.metadata.get_track(track_id)

    def corners(self, track_id):
        meta = self.metadata.get_track(track_id)
        ident = self.identify(track_id)
        if meta is None:
            return {**ident, "available": False, "expected_length_m": None, "calibration": {},
                    "has_corner_distances": False, "corners": [], "complexes": []}
        rng = lambda r: list(r) if r else None
        return {
            **ident, "available": True, "expected_length_m": meta.expected_length_m,
            "calibration": meta.calibration, "has_corner_distances": meta.has_corner_distances,
            "corners": [{"number": c.number, "label": f"T{c.number}", "name": c.name,
                         "range_m": rng(c.range_m), "representative_m": c.representative_m}
                        for c in meta.corners],
            "complexes": [{"label": cx.label, "corners": list(cx.corners), "name": cx.name,
                           "range_m": rng(cx.range_m), "representative_m": cx.representative_m}
                          for cx in meta.complexes],
        }

    # --------------------------------------------------------------------- live

    def activate(self, info, game_year=None):
        """The game reported this circuit: load or create its profile. Returns its identity,
        or None when the game reports no track. Writes only if something actually changed."""
        if info.track_id == UNKNOWN_TRACK_ID:
            return None
        ident = self.identify(info.track_id)
        with self._lock:
            previous = self.profiles.get(info.track_id)
            profile = copy.deepcopy(previous) if previous else new_profile(info.track_id, ident["name"])
            profile["name"] = ident["name"]
            if info.track_length_m > 0:
                profile["track_length_m"] = info.track_length_m
            if game_year:
                profile["game_year"] = game_year
            self.profiles.save_if_changed(profile, previous)
        return ident

    # ----------------------------------------------------------- lap association

    def lap_track_info(self, lap_id):
        """Track of a lap for the API: {track_id, track_name, track_source}; all None if unknown."""
        track = self.lap_tracks.get(lap_id)
        if track is None:
            return {"track_id": None, "track_name": None, "track_source": None}
        return {"track_id": track.track_id, "track_name": self.metadata.display_name(track.track_id),
                "track_source": track.source}

    def register_recorded_lap(self, lap_id, info, game_year=None):
        """A lap was just saved while the game reported `info`: remember its circuit."""
        if info.track_id == UNKNOWN_TRACK_ID:
            return None
        with self._lock:
            self.lap_tracks.set(lap_id, LapTrack(info.track_id, SOURCE_TELEMETRY, info.track_length_m,
                                                 game_year, info.session_type))
            return self.refresh(info.track_id)

    def assign_lap(self, lap_id, track_id):
        """Manually assign a lap with no track (or a manual assignment) to a known circuit.
        The lap's telemetry file is not touched. Raises FileNotFoundError, UnknownTrackError,
        TrackConflictError."""
        if not (self.laps_dir / f"{lap_id}.csv").is_file():
            raise FileNotFoundError(lap_id)
        if not self.metadata.is_known(track_id):
            raise UnknownTrackError(f"track {track_id} is not a known F1 25 circuit")
        with self._lock:
            existing = self.lap_tracks.get(lap_id)
            if existing is not None and existing.source == SOURCE_TELEMETRY:
                raise TrackConflictError("this lap's circuit was reported by the game and cannot be changed")
            if existing is not None and existing.track_id == track_id:
                return self.lap_track_info(lap_id)
            self.lap_tracks.set(lap_id, LapTrack(int(track_id), SOURCE_MANUAL))
            self.refresh(track_id)
            if existing is not None:
                self.refresh(existing.track_id)  # the lap left its previous (manually assigned) circuit
            return self.lap_track_info(lap_id)

    def assign_session(self, session_uid, track_id):
        """Assign every lap of a session that the game did not tag. Returns {assigned, skipped}."""
        if not self.metadata.is_known(track_id):
            raise UnknownTrackError(f"track {track_id} is not a known F1 25 circuit")
        assigned, skipped = [], []
        for path in sorted(self.laps_dir.glob(f"{session_uid}_*.csv")) if self.laps_dir.is_dir() else []:
            try:
                self.assign_lap(path.stem, track_id)
                assigned.append(path.stem)
            except TrackConflictError:
                skipped.append(path.stem)
        return {"assigned": assigned, "skipped": skipped}

    # ------------------------------------------------------------------ profiles

    def _laps_on(self, track_id):
        laps = []
        for lap_id, track in self.lap_tracks.lap_ids_with_track().items():
            if track.track_id != int(track_id):
                continue
            try:
                laps.append((lap_id, load_lap(self.laps_dir / f"{lap_id}.csv")))
            except CompareError:
                continue  # unreadable or missing lap file: not counted
        laps.sort(key=lambda item: (item[1].session or "", item[1].lap_number, item[0]))
        return laps

    @staticmethod
    def _stats(laps):
        valid = [(lid, lap) for lid, lap in laps if not lap.invalid]
        timed = [(lap.lap_time_ms, lid) for lid, lap in valid if lap.lap_time_ms is not None]
        best = min(timed) if timed else None
        return {
            "sessions": len({lap.session or lid for lid, lap in laps}),
            "valid_laps": len(valid),
            "pb": {"lap_id": best[1], "lap_time_ms": best[0]} if best else None,
        }

    def _observe(self, lap):
        """Generic driving events of one lap, via the existing track-agnostic detector."""
        try:
            rows = compare_laps(lap, lap)  # resamples the lap onto the 5 m grid
        except CompareError:
            return None
        events = detect_events([r["distance_m"] for r in rows], [r["ref_speed_kmh"] for r in rows],
                               [r["ref_throttle"] for r in rows], [r["ref_brake"] for r in rows])
        return [ObservedEvent(e.min_speed_m, e.brake_start_m) for e in events]

    def _learn(self, profile, laps):
        learning = profile["learning"]
        learned = set(learning["learned_lap_ids"])
        pb = profile["stats"]["pb"]
        for lap_id, lap in laps:
            if lap.invalid or lap_id in learned:
                continue  # invalid laps never teach; each lap teaches once
            if pb and lap.lap_time_ms and lap.lap_time_ms > pb["lap_time_ms"] * self.learning.max_lap_time_ratio:
                continue  # far slower than the best lap: likely a crash, stop or test lap
            observed = self._observe(lap)
            if observed is None:
                continue
            learning["events"], _ = update_learned_events(
                learning["events"], learning["laps_learned"], observed, self.learning)
            learning["laps_learned"] += 1
            learning["learned_lap_ids"].append(lap_id)

    def refresh(self, track_id):
        """Recompute a circuit's statistics from its recorded laps and learn from new valid laps."""
        with self._lock:
            previous = self.profiles.get(track_id)
            profile = copy.deepcopy(previous) if previous else new_profile(int(track_id), self.metadata.display_name(track_id))
            profile["name"] = self.metadata.display_name(track_id)
            laps = self._laps_on(track_id)
            profile["stats"] = self._stats(laps)
            self._learn(profile, laps)
            self.profiles.save_if_changed(profile, previous)
            self._refresh_map(track_id, profile, laps)
            return profile

    # ---------------------------------------------------------------- track map

    def has_positions(self, lap_id):
        return self.positions.exists(lap_id)

    def _map_path(self, track_id):
        return self.maps_dir / f"{int(track_id)}.json"

    def _read_map(self, track_id):
        try:
            stored = json.loads(self._map_path(track_id).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return stored if isinstance(stored, dict) and stored.get("track_id") == int(track_id) else None

    def _lap_input(self, lap_id, lap):
        path = self.positions.read(lap_id)
        if path is None:
            return None
        track = self.lap_tracks.get(lap_id)
        return LapInput(lap_id, path, tuple(lap.distance), tuple(lap.steer),
                        track.track_length_m if track else None)

    def _refresh_map(self, track_id, profile, laps):
        """Rebuild the circuit trace from this circuit's valid laps that have positions.
        Only this circuit's laps are ever used. Skipped when the set of laps is unchanged."""
        candidates = [(lid, lap) for lid, lap in laps if not lap.invalid and self.positions.exists(lid)]
        if not candidates:
            return
        signature = sorted(lid for lid, _ in candidates)
        stored = self._read_map(track_id)
        if stored is not None and stored.get("candidates") == signature:
            return
        inputs = [li for li in (self._lap_input(lid, lap) for lid, lap in candidates) if li is not None]
        built = build_geometry(inputs, profile.get("track_length_m"), self.geometry) if inputs else None
        result = built or {"laps": [], "rejected": [], "driver_path": None}
        unreadable = [lid for lid, _ in candidates if lid not in {li.lap_id for li in inputs}]
        result["rejected"] = result.get("rejected", []) + [
            {"lap_id": lid, "reason": "position file is unreadable"} for lid in unreadable]
        atomic_write_json(self._map_path(track_id), {
            "schema_version": 1,
            "track_id": int(track_id),
            "track_length_m": profile.get("track_length_m"),
            "generated_at": now_iso(),
            "candidates": signature,
            "kind": "driver_path",
            "centerline": {"available": False,
                           "reason": "A centerline cannot be derived from the path one driver chose to take."},
            **result,
        })

    def get_map(self, track_id):
        """The stored circuit trace for the API, or an explanation of why there is none."""
        stored = self._read_map(track_id)
        if stored is None:
            return {"track_id": int(track_id), "available": False, "reason": "no_positions",
                    "message": "No position data has been recorded for this circuit yet. "
                               "Record laps with Motion data enabled.",
                    "driver_path": None, "centerline": {"available": False}, "laps": [], "rejected": []}
        available = stored.get("driver_path") is not None
        return {**stored, "available": available,
                "reason": None if available else "no_usable_laps",
                "message": None if available else "Position data exists, but no lap was complete and consistent enough to build a trace."}

    def lap_path(self, lap_id):
        """One lap's own recorded path (its racing line) with the orientation derived from its
        steering. Not smoothed and not merged with any other lap."""
        track = self.lap_track_info(lap_id)
        base = {"lap_id": lap_id, "track_id": track["track_id"]}
        path = self.positions.read(lap_id)
        if path is None:
            return {**base, "available": False, "reason": "no_positions",
                    "message": "This lap has no recorded position data."}
        orient, axes = None, axes_report(path.x, path.y, path.z, self.geometry)
        try:
            lap = load_lap(self.laps_dir / f"{lap_id}.csv")
            grid = [path.distance[0] + i * self.geometry.step_m
                    for i in range(int((path.distance[-1] - path.distance[0]) / self.geometry.step_m) + 1)]
            xs, _, zs = resample(path, grid)
            r = orientation(grid, xs, zs, tuple(lap.distance), tuple(lap.steer))
            orient = {"mirror_z": bool(r is not None and r < 0), "r": round(r, 3) if r is not None else None,
                      "verified": bool(r is not None and abs(r) >= self.geometry.min_orientation_r),
                      "laps_checked": 1 if r is not None else 0}
        except CompareError:
            pass
        return {**base, "available": True, "point_count": len(path),
                "distance_m": [round(v, 1) for v in path.distance],
                "x": [round(v, 2) for v in path.x], "y": [round(v, 2) for v in path.y],
                "z": [round(v, 2) for v in path.z],
                "axes": axes,
                "orientation": orient or {"mirror_z": False, "r": None, "verified": False, "laps_checked": 0}}

    def _summary(self, profile, active_track_id=None):
        tid = profile["track_id"]
        meta = self.metadata.get_track(tid)
        pb = profile["stats"]["pb"]
        return {
            **self.identify(tid),
            "track_length_m": profile.get("track_length_m"),
            "game_year": profile.get("game_year"),
            "has_corner_metadata": meta is not None,
            "has_corner_distances": bool(meta and meta.has_corner_distances),
            "corner_count": len(meta.corners) if meta else 0,
            "stats": {
                "sessions": profile["stats"]["sessions"],
                "valid_laps": profile["stats"]["valid_laps"],
                "pb": {**pb, "lap_time": format_lap_time(pb["lap_time_ms"])} if pb else None,
            },
            "is_active": active_track_id is not None and tid == active_track_id,
            "has_map": self._map_path(tid).is_file() and self.get_map(tid)["available"],
        }

    def unassigned_lap_count(self):
        if not self.laps_dir.is_dir():
            return 0
        tagged = self.lap_tracks.lap_ids_with_track()
        return sum(1 for p in self.laps_dir.glob("*.csv") if p.stem not in tagged)

    def list_tracks(self, active_track_id=None):
        """Circuits with a saved profile (the track selector's options) and the unassigned lap count."""
        with self._lock:
            tracks = [self._summary(self.refresh(tid), active_track_id) for tid in self.profiles.list_ids()]
        tracks.sort(key=lambda t: t["name"].lower())
        return {"tracks": tracks, "active_track_id": active_track_id,
                "unassigned_laps": self.unassigned_lap_count()}

    def track_detail(self, track_id, active_track_id=None):
        """One circuit: summary, learned events (each mapped to a corner by distance), static
        metadata status. None if the circuit has no saved profile."""
        with self._lock:
            if self.profiles.get(track_id) is None:
                return None
            profile = self.refresh(track_id)
        meta = self.metadata.get_track(track_id)
        events = []
        for e in profile["learning"]["events"]:
            corner = map_point(meta, e["min_speed_m"]["median"])
            events.append({
                "id": e["id"],
                "min_speed_m": e["min_speed_m"],
                "brake_start_m": e["brake_start_m"],
                "observations": e["observations_count"],
                "outliers_rejected": e["outliers_rejected"],
                "spread_m": e["min_speed_m"]["spread"],
                "confidence": e["confidence"],
                "corner": {"status": corner.status, "label": corner.label, "corners": list(corner.corners)},
            })
        return {
            **self._summary(profile, active_track_id),
            "created_at": profile["created_at"],
            "updated_at": profile["updated_at"],
            "laps_learned": profile["learning"]["laps_learned"],
            "learned_events": events,
            "corner_metadata": {"available": meta is not None,
                                "status": meta.calibration_status if meta else None,
                                "has_corner_distances": bool(meta and meta.has_corner_distances)},
        }
