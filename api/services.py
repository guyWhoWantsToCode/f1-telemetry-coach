"""Glue between the API and the existing analysis modules.

All telemetry logic stays in lap_compare.py and corner_analysis.py; this module only
loads files, calls them, and shapes the results as JSON-friendly dicts.
"""

from dataclasses import asdict, replace

from api.storage import DataStore, NotFoundError
from corner_analysis import CornerError, Thresholds, analyze, load_aligned
from tracks.corners import map_comparison_events
from lap_compare import CompareError, check_laps, compare_laps, load_lap, save_comparison, summarize

COMPARISON_SEPARATOR = "__vs__"  # how lap_compare.save_comparison names its files


class UnprocessableError(ValueError):
    """The request is valid but the laps cannot be compared / analysed."""


def format_lap_time(ms):
    if ms is None:
        return None
    minutes, rest = divmod(ms, 60000)
    return f"{minutes}:{rest / 1000:06.3f}"


NO_TRACK = {"track_id": None, "track_name": None, "track_source": None}


def lap_metadata(lap, tracks=None):
    """Lap summary. With a TrackService it also says which circuit the lap belongs to (or that
    it is unknown: laps recorded before track identity existed)."""
    return {
        **(tracks.lap_track_info(lap.path.stem) if tracks is not None else NO_TRACK),
        "has_positions": bool(tracks is not None and tracks.has_positions(lap.path.stem)),
        "id": lap.path.stem,
        "filename": lap.path.name,
        "session_uid": lap.session,
        "lap_number": lap.lap_number,
        "lap_time_ms": lap.lap_time_ms,
        "lap_time": format_lap_time(lap.lap_time_ms),
        "valid": not lap.invalid,
        "samples": len(lap.distance),
        "start_distance_m": lap.start,
        "end_distance_m": lap.end,
    }


def list_laps(store, tracks=None):
    laps, skipped = [], []
    for path in store.lap_paths():
        try:
            laps.append(lap_metadata(load_lap(path), tracks))
        except CompareError as e:
            skipped.append({"id": path.stem, "error": str(e)})
    laps.sort(key=lambda m: (m["session_uid"] or "", m["lap_number"]))
    return {"laps": laps, "skipped": skipped}


def lap_detail(store, lap_id, tracks=None):
    path = store.lap_path(lap_id)
    try:
        lap = load_lap(path)
    except CompareError as e:
        raise UnprocessableError(str(e)) from e
    return {**lap_metadata(lap, tracks), "samples_data": store.read_columns(path)}


def _summary(rows, ref, cmp_):
    s = summarize(rows)
    total = None
    if ref.lap_time_ms is not None and cmp_.lap_time_ms is not None:
        total = cmp_.lap_time_ms - ref.lap_time_ms  # official lap times, from the filenames
    point = lambda hit: None if hit is None else {"distance_m": hit[0], "delta_ms": hit[1]}
    return {
        "reference_lap_time_ms": ref.lap_time_ms,
        "comparison_lap_time_ms": cmp_.lap_time_ms,
        "total_difference_ms": total,  # positive = comparison slower; None if a time is unknown
        "final_delta_ms": s["final_delta_ms"],
        "final_distance_m": s["final_distance_m"],
        "largest_loss": point(s["loss"]),
        "largest_gain": point(s["gain"]),
        "points": len(rows),
        "start_distance_m": rows[0]["distance_m"],
        "end_distance_m": rows[-1]["distance_m"],
    }


def run_comparison(store, reference_id, comparison_id, allow_invalid=False, tracks=None):
    """Compare two recorded laps with lap_compare and save the aligned CSV."""
    if reference_id == comparison_id:
        raise UnprocessableError("reference and comparison must be different laps")
    ref_path, cmp_path = store.lap_path(reference_id), store.lap_path(comparison_id)
    try:
        ref, cmp_ = load_lap(ref_path), load_lap(cmp_path)
        warnings = check_laps(ref, cmp_, allow_invalid)
        rows = compare_laps(ref, cmp_)
    except CompareError as e:
        raise UnprocessableError(str(e)) from e
    path = save_comparison(rows, ref, cmp_, store.comparisons_dir)
    return {
        "id": path.stem,
        "reference": lap_metadata(ref, tracks),
        "comparison": lap_metadata(cmp_, tracks),
        "warnings": warnings,
        "summary": _summary(rows, ref, cmp_),
    }


def _laps_of(store, comparison_id):
    """The two lap files behind a saved comparison, if they still exist (else None)."""
    ref_id, sep, cmp_id = comparison_id.partition(COMPARISON_SEPARATOR)
    if not sep:
        return None, None
    laps = []
    for lap_id in (ref_id, cmp_id):
        try:
            laps.append(load_lap(store.lap_path(lap_id)))
        except (NotFoundError, CompareError, ValueError):
            laps.append(None)
    return laps[0], laps[1]


def comparison_detail(store, comparison_id, tracks=None):
    path = store.comparison_path(comparison_id)
    data = store.read_columns(path)
    if not data.get("distance_m"):
        raise UnprocessableError(f"comparison {comparison_id} has no rows")
    rows = [{"distance_m": d, "delta_ms": t} for d, t in zip(data["distance_m"], data["delta_ms"])]
    ref, cmp_ = _laps_of(store, comparison_id)
    out = {"id": comparison_id, "reference": ref and lap_metadata(ref, tracks),
           "comparison": cmp_ and lap_metadata(cmp_, tracks), "data": data}
    if ref and cmp_:
        out["summary"] = _summary(rows, ref, cmp_)
    else:  # lap files are gone: summarize from the aligned data alone
        s = summarize(rows)
        out["summary"] = {"final_delta_ms": s["final_delta_ms"], "final_distance_m": s["final_distance_m"],
                          "points": len(rows)}
    return out


def _event_json(ev, corner=None, track_known=False):
    """One event row. The generic event identity (name, number, status, differences) is always
    present; corner fields are added from the corner mapping when a track is known."""
    d = asdict(ev)  # dataclass fields incl. nested events
    d.update(
        comparable=ev.comparable,
        brake_start_diff_m=ev.brake_start_diff_m, min_speed_diff_kmh=ev.min_speed_diff_kmh,
        pickup_diff_m=ev.pickup_diff_m, full_throttle_diff_m=ev.full_throttle_diff_m,
        event_number=int(ev.name.rsplit(" ", 1)[-1]),
    )
    if corner is None or not track_known:
        d.update(corner_label=None, corner_status="unavailable", corner_confidence=None,
                 corner_numbers=[], corner_candidates=[], corner_reason="circuit is not known for these laps")
    else:
        d.update(corner_label=corner.label, corner_status=corner.status,
                 corner_confidence=corner.confidence if corner.label else None,
                 corner_numbers=list(corner.corners), corner_candidates=list(corner.candidates),
                 corner_reason=corner.reason)
    return d


def _comparison_track(store, comparison_id, tracks):
    """The circuit shared by both laps of a comparison, or None if unknown / they differ."""
    if tracks is None:
        return None, "no track memory"
    ref, cmp_ = _laps_of(store, comparison_id)
    if ref is None or cmp_ is None:
        return None, "the lap files are no longer available"
    a, b = tracks.lap_track_info(ref.path.stem), tracks.lap_track_info(cmp_.path.stem)
    if a["track_id"] is None or b["track_id"] is None:
        return None, "the circuit of these laps is unknown"
    if a["track_id"] != b["track_id"]:
        return None, "the two laps are from different circuits"
    return a, None


def comparison_events(store, comparison_id, min_drop=None, merge_rise=None, brake_on=None, tracks=None):
    """Run corner_analysis on a saved comparison. Optional args override thresholds. When the
    laps' circuit is known, each event also carries the corner it was mapped to (by distance)."""
    path = store.comparison_path(comparison_id)
    overrides = {k: v for k, v in (("min_drop_kmh", min_drop), ("merge_rise_kmh", merge_rise),
                                   ("brake_on", brake_on)) if v is not None}
    th = replace(Thresholds(), **overrides)
    try:
        results = analyze(load_aligned(path), th)
    except CornerError as e:
        raise UnprocessableError(str(e)) from e

    track, why_not = _comparison_track(store, comparison_id, tracks)
    meta = tracks.corner_metadata(track["track_id"]) if track else None
    matches = map_comparison_events(meta, results) if track else [None] * len(results)
    return {
        "comparison_id": comparison_id, "thresholds": asdict(th),
        "track": {**track, "has_corner_metadata": meta is not None,
                  "has_corner_distances": bool(meta and meta.has_corner_distances),
                  "reason": None} if track else {**NO_TRACK, "has_corner_metadata": False,
                                                 "has_corner_distances": False, "reason": why_not},
        "count": len(results),
        "events": [_event_json(r, m, track is not None) for r, m in zip(results, matches)],
    }
