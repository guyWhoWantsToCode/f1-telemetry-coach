"""Which circuit each recorded lap belongs to, kept beside the lap files.

For lap `<id>.csv` the association is a small JSON sidecar `<id>.meta.json` in the same
folder. The telemetry CSV is never modified, and a lap without a sidecar (every lap
recorded before track identity existed) simply has an unknown track. Nothing is ever
inferred from a lap's length or file name.
"""

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

SCHEMA_VERSION = 1
SOURCE_TELEMETRY = "telemetry"  # reported by the game's Session packet when the lap was recorded
SOURCE_MANUAL = "manual"  # assigned by the user afterwards


@dataclass(frozen=True)
class LapTrack:
    track_id: int
    source: str
    track_length_m: int = None
    game_year: int = None
    session_type: int = None


def atomic_write_json(path, data):
    """Write JSON so a crash can never leave a half-written file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


class LapTrackIndex:
    def __init__(self, laps_dir):
        self.laps_dir = Path(laps_dir)

    def _path(self, lap_id):
        return self.laps_dir / f"{lap_id}.meta.json"

    def get(self, lap_id):
        """The lap's track association, or None when it has none (or the sidecar is unreadable)."""
        try:
            raw = json.loads(self._path(lap_id).read_text(encoding="utf-8"))
            return LapTrack(int(raw["track_id"]), str(raw["source"]), raw.get("track_length_m"),
                            raw.get("game_year"), raw.get("session_type"))
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def set(self, lap_id, track):
        atomic_write_json(self._path(lap_id), {
            "schema_version": SCHEMA_VERSION,
            "track_id": track.track_id,
            "source": track.source,
            "track_length_m": track.track_length_m,
            "game_year": track.game_year,
            "session_type": track.session_type,
        })

    def lap_ids_with_track(self):
        """{lap_id: LapTrack} for every sidecar present."""
        if not self.laps_dir.is_dir():
            return {}
        found = {}
        for path in self.laps_dir.glob("*.meta.json"):
            lap_id = path.name[: -len(".meta.json")]
            track = self.get(lap_id)
            if track is not None:
                found[lap_id] = track
        return found
