"""Per-lap world positions recorded from Motion packets: data/positions/<lap_id>.csv.

A sidecar to the lap CSV (same id), one row per saved lap sample:
    lap_distance_m, pos_x, pos_y, pos_z      (metres; blank cells where no position was matched)
The lap CSV is never changed, and laps recorded before this existed simply have no sidecar.
"""

import csv
import math
from dataclasses import dataclass
from pathlib import Path

REQUIRED = ("lap_distance_m", "pos_x", "pos_y", "pos_z")


@dataclass(frozen=True)
class LapPath:
    distance: tuple  # lap distance of each point, metres, strictly increasing
    x: tuple
    y: tuple
    z: tuple

    def __len__(self):
        return len(self.distance)


class PositionStore:
    def __init__(self, directory):
        self.directory = Path(directory)

    def path(self, lap_id):
        return self.directory / f"{lap_id}.csv"

    def exists(self, lap_id):
        return self.path(lap_id).is_file()

    def read(self, lap_id):
        """The lap's recorded path, or None when there is none or the file is unusable.
        Rows without a position are skipped (never filled in)."""
        try:
            with open(self.path(lap_id), newline="") as f:
                reader = csv.DictReader(f)
                if any(c not in (reader.fieldnames or []) for c in REQUIRED):
                    return None
                rows = []
                for row in reader:
                    if any(row[c] in ("", None) for c in REQUIRED):
                        continue
                    values = [float(row[c]) for c in REQUIRED]
                    if not all(math.isfinite(v) for v in values):
                        return None
                    rows.append(values)
        except (OSError, ValueError):
            return None
        if len(rows) < 2 or any(b[0] <= a[0] for a, b in zip(rows, rows[1:])):
            return None
        d, x, y, z = zip(*rows)
        return LapPath(d, x, y, z)
