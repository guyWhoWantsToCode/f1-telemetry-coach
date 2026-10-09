"""Persistent learned track profiles: data/tracks/<f1_track_id>.json.

A profile is what the application has *learned and recorded* about one circuit. It is keyed by
the official F1 track ID. It never contains static circuit facts such as corner numbers or
distances; it only holds a pointer (`corner_metadata`) to them.

    {
      "schema_version": 1,
      "track_id": 15,
      "name": "Circuit of the Americas",
      "track_length_m": 5513,            # as last reported by the game
      "game_year": 2025,                 # UDP packet format
      "corner_metadata": {"track_id": 15},   # reference into track_metadata/, not a copy
      "stats": {"sessions": 1, "valid_laps": 2, "pb": {"lap_id": "...", "lap_time_ms": 100146}},
      "learning": {"laps_learned": 2, "learned_lap_ids": [...], "events": [...]},
      "created_at": "...", "updated_at": "..."
    }

`stats` is derived from the recorded lap files (see TrackService.refresh) and is rewritten
from scratch each time, never incremented, so it cannot double count.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from tracks.lap_tracks import atomic_write_json

SCHEMA_VERSION = 1


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_profile(track_id, name, track_length_m=None, game_year=None):
    stamp = now_iso()
    return {
        "schema_version": SCHEMA_VERSION,
        "track_id": track_id,
        "name": name,
        "track_length_m": track_length_m,
        "game_year": game_year,
        "corner_metadata": {"track_id": track_id},
        "stats": {"sessions": 0, "valid_laps": 0, "pb": None},
        "learning": {"laps_learned": 0, "learned_lap_ids": [], "events": []},
        "created_at": stamp,
        "updated_at": stamp,
    }


def _comparable(profile):
    """Everything except the timestamp, to decide whether a save would change anything."""
    return {k: v for k, v in profile.items() if k != "updated_at"}


class ProfileStore:
    def __init__(self, directory):
        self.directory = Path(directory)

    def _path(self, track_id):
        return self.directory / f"{int(track_id)}.json"

    def get(self, track_id):
        """The stored profile, or None if there is none (or the file is unreadable)."""
        try:
            profile = json.loads(self._path(track_id).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return profile if isinstance(profile, dict) and profile.get("track_id") == int(track_id) else None

    def list_ids(self):
        if not self.directory.is_dir():
            return []
        return sorted(int(p.stem) for p in self.directory.glob("*.json") if p.stem.lstrip("-").isdigit())

    def save(self, profile):
        atomic_write_json(self._path(profile["track_id"]), profile)

    def save_if_changed(self, profile, previous):
        """Write only when something other than the timestamp differs. Returns True if written."""
        if previous is not None and _comparable(profile) == _comparable(previous):
            return False
        profile["updated_at"] = now_iso()
        self.save(profile)
        return True
