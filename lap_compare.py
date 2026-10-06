"""Compare two recorded lap CSVs (from lap_recorder.py) by lap distance.

    python lap_compare.py reference.csv comparison.csv

Both laps are linearly interpolated onto a common distance grid (every GRID_STEP_M metres)
covering ONLY the distance range both laps contain; nothing is extrapolated.

Delta convention:  delta = comparison time - reference time at the same distance.
    positive delta = comparison lap is SLOWER than the reference
    negative delta = comparison lap is FASTER than the reference
"""

import argparse
import csv
import math
import re
import sys
from bisect import bisect_right
from pathlib import Path

GRID_STEP_M = 5.0
LENGTH_MISMATCH_WARN_M = 25.0  # laps ending this far apart get a warning
MIN_SHARED_FRACTION = 0.9  # shared distance must cover this much of the longer lap
OUT_DIR = Path("data/comparisons")

REQUIRED_COLUMNS = [
    "lap", "lap_distance_m", "lap_time_ms", "speed_kmh", "throttle", "brake",
    "steer", "gear", "invalid",
]
OUT_COLUMNS = [
    "distance_m", "ref_time_ms", "cmp_time_ms", "delta_ms",
    "ref_speed_kmh", "cmp_speed_kmh", "ref_throttle", "cmp_throttle",
    "ref_brake", "cmp_brake", "ref_steer", "cmp_steer", "ref_gear", "cmp_gear",
]

_NAME_RE = re.compile(r"^(?P<session>[0-9a-f]{16})_lap(?P<lap>\d+)_(?:(?P<m>\d+)m(?P<s>\d+\.\d+)s|unknown)")


class CompareError(Exception):
    """The laps cannot be compared (bad file, invalid lap, laps don't overlap...)."""


class Lap:
    def __init__(self, path, rows):
        self.path = Path(path)
        self.distance = [r["lap_distance_m"] for r in rows]
        self.time_ms = [r["lap_time_ms"] for r in rows]
        self.speed = [r["speed_kmh"] for r in rows]
        self.throttle = [r["throttle"] for r in rows]
        self.brake = [r["brake"] for r in rows]
        self.steer = [r["steer"] for r in rows]
        self.gear = [r["gear"] for r in rows]
        self.invalid = any(r["invalid"] for r in rows)
        self.lap_number = rows[0]["lap"]
        m = _NAME_RE.match(self.path.name)
        self.session = m["session"] if m else None
        # Official lap time only exists in the filename (the CSV stops before the line).
        self.lap_time_ms = round((int(m["m"]) * 60 + float(m["s"])) * 1000) if m and m["m"] else None

    @property
    def start(self):
        return self.distance[0]

    @property
    def end(self):
        return self.distance[-1]


def load_lap(path):
    """Load a recorder CSV. Raises CompareError if it is unreadable or malformed."""
    try:
        with open(path, newline="") as f:
            reader = csv.DictReader(f)
            missing = [c for c in REQUIRED_COLUMNS if c not in (reader.fieldnames or [])]
            if missing:
                raise CompareError(f"{path}: missing columns {missing}")
            rows = [
                {
                    "lap": int(r["lap"]), "lap_distance_m": float(r["lap_distance_m"]),
                    "lap_time_ms": float(r["lap_time_ms"]), "speed_kmh": float(r["speed_kmh"]),
                    "throttle": float(r["throttle"]), "brake": float(r["brake"]),
                    "steer": float(r["steer"]), "gear": int(r["gear"]),
                    "invalid": int(r["invalid"]) != 0,
                }
                for r in reader
            ]
    except OSError as e:
        raise CompareError(f"cannot read {path}: {e}") from e
    except ValueError as e:
        raise CompareError(f"{path}: bad value in CSV ({e})") from e
    if len(rows) < 2:
        raise CompareError(f"{path}: needs at least 2 rows, found {len(rows)}")
    dists = [r["lap_distance_m"] for r in rows]
    if any(b <= a for a, b in zip(dists, dists[1:])):
        raise CompareError(f"{path}: lap distance is not strictly increasing")
    return Lap(path, rows)


def _interp(xs, ys, x):
    """Linear interpolation; x must lie within [xs[0], xs[-1]] (never extrapolates)."""
    if x < xs[0] - 1e-6 or x > xs[-1] + 1e-6:
        raise ValueError("interpolation outside recorded range")
    x = min(max(x, xs[0]), xs[-1])  # absorb float rounding at the very edges
    i = bisect_right(xs, x)
    if i == len(xs):
        return ys[-1]
    x0, x1, y0, y1 = xs[i - 1], xs[i], ys[i - 1], ys[i]
    return y0 + (y1 - y0) * (x - x0) / (x1 - x0)


def _hold(xs, ys, x):
    """Value of the last sample at or before x (for gear, which can't be interpolated)."""
    return ys[max(bisect_right(xs, x) - 1, 0)]


def common_grid(ref, cmp_, step=GRID_STEP_M):
    """Distances (multiples of `step`) inside the range covered by BOTH laps."""
    lo = max(ref.start, cmp_.start)
    hi = min(ref.end, cmp_.end)
    first = math.ceil(lo / step - 1e-9)
    last = math.floor(hi / step + 1e-9)
    return [round(k * step, 6) for k in range(first, last + 1)]


def check_laps(ref, cmp_, allow_invalid=False):
    """Return a list of warning strings; raise CompareError for fatal problems."""
    warnings = []
    for role, lap in (("reference", ref), ("comparison", cmp_)):
        if lap.invalid:
            if not allow_invalid:
                raise CompareError(
                    f"{role} lap {lap.path.name} is INVALID (track limits). "
                    "Use --allow-invalid to compare it anyway.")
            warnings.append(f"{role} lap is INVALID - its times are not a legal lap time")
    if ref.session and cmp_.session and ref.session != cmp_.session:
        warnings.append("laps are from different sessions (check they are the same track/car)")
    if abs(ref.end - cmp_.end) > LENGTH_MISMATCH_WARN_M:
        warnings.append(
            f"lap lengths differ: reference ends at {ref.end:.0f} m, comparison at "
            f"{cmp_.end:.0f} m; only the shared distance is compared")
    shared = min(ref.end, cmp_.end) - max(ref.start, cmp_.start)
    longest = max(ref.end - ref.start, cmp_.end - cmp_.start)
    if shared < MIN_SHARED_FRACTION * longest:
        raise CompareError(
            f"laps overlap for only {max(shared, 0):.0f} m of {longest:.0f} m - "
            "they look like different tracks or partial laps")
    return warnings


def compare_laps(ref, cmp_, step=GRID_STEP_M):
    """Aligned rows (dicts keyed by OUT_COLUMNS) over the shared distance range."""
    grid = common_grid(ref, cmp_, step)
    if len(grid) < 2:
        raise CompareError("laps share too little distance to compare")
    rows = []
    for d in grid:
        rt = _interp(ref.distance, ref.time_ms, d)
        ct = _interp(cmp_.distance, cmp_.time_ms, d)
        rows.append({
            "distance_m": d,
            "ref_time_ms": rt, "cmp_time_ms": ct, "delta_ms": ct - rt,  # + = comparison slower
            "ref_speed_kmh": _interp(ref.distance, ref.speed, d),
            "cmp_speed_kmh": _interp(cmp_.distance, cmp_.speed, d),
            "ref_throttle": _interp(ref.distance, ref.throttle, d),
            "cmp_throttle": _interp(cmp_.distance, cmp_.throttle, d),
            "ref_brake": _interp(ref.distance, ref.brake, d),
            "cmp_brake": _interp(cmp_.distance, cmp_.brake, d),
            "ref_steer": _interp(ref.distance, ref.steer, d),
            "cmp_steer": _interp(cmp_.distance, cmp_.steer, d),
            "ref_gear": _hold(ref.distance, ref.gear, d),
            "cmp_gear": _hold(cmp_.distance, cmp_.gear, d),
        })
    return rows


def summarize(rows):
    """Largest accumulated loss (max delta) and gain (min delta), or None if there is none."""
    worst = max(rows, key=lambda r: r["delta_ms"])
    best = min(rows, key=lambda r: r["delta_ms"])
    return {
        "loss": (worst["distance_m"], worst["delta_ms"]) if worst["delta_ms"] > 0 else None,
        "gain": (best["distance_m"], best["delta_ms"]) if best["delta_ms"] < 0 else None,
        "final_delta_ms": rows[-1]["delta_ms"],
        "final_distance_m": rows[-1]["distance_m"],
    }


def save_comparison(rows, ref, cmp_, out_dir=OUT_DIR):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{ref.path.stem}__vs__{cmp_.path.stem}.csv"
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(OUT_COLUMNS)
        for r in rows:
            writer.writerow([round(r[c], 4) if isinstance(r[c], float) else r[c] for c in OUT_COLUMNS])
    return path


def _fmt_time(ms):
    if ms is None:
        return "unknown (not in filename)"
    minutes, rest = divmod(ms, 60000)
    return f"{int(minutes)}:{rest / 1000:06.3f}"


def _fmt_delta(ms):
    return f"{ms / 1000:+.3f} s"


def main(argv=None):
    ap = argparse.ArgumentParser(description="Compare two recorded F1 25 laps by distance.")
    ap.add_argument("reference", help="reference lap CSV (the lap to compare against)")
    ap.add_argument("comparison", help="comparison lap CSV")
    ap.add_argument("--allow-invalid", action="store_true",
                    help="compare invalid laps anyway (with a warning)")
    ap.add_argument("--out-dir", default=str(OUT_DIR), help="where to save the aligned CSV")
    args = ap.parse_args(argv)

    try:
        ref, cmp_ = load_lap(args.reference), load_lap(args.comparison)
        warnings = check_laps(ref, cmp_, args.allow_invalid)
        rows = compare_laps(ref, cmp_)
    except CompareError as e:
        print(f"Error: {e}")
        return 1

    for w in warnings:
        print(f"WARNING: {w}")
    summary = summarize(rows)
    print(f"Reference : {ref.path.name}  lap time {_fmt_time(ref.lap_time_ms)}")
    print(f"Comparison: {cmp_.path.name}  lap time {_fmt_time(cmp_.lap_time_ms)}")
    if ref.lap_time_ms is not None and cmp_.lap_time_ms is not None:
        print(f"Total lap-time difference: {_fmt_delta(cmp_.lap_time_ms - ref.lap_time_ms)}"
              "  (+ = comparison slower)")
    else:
        print("Total lap-time difference: unavailable (a lap time is missing from a filename)")
    print(f"Delta at end of shared distance ({summary['final_distance_m']:.0f} m): "
          f"{_fmt_delta(summary['final_delta_ms'])}")
    for label, key in (("Largest accumulated time LOSS", "loss"), ("Largest accumulated time GAIN", "gain")):
        hit = summary[key]
        print(f"{label}: " + (f"{_fmt_delta(hit[1])} at {hit[0]:.0f} m" if hit else "none"))
    print(f"Compared {len(rows)} points every {GRID_STEP_M:.0f} m "
          f"({rows[0]['distance_m']:.0f}-{rows[-1]['distance_m']:.0f} m)")
    print(f"Saved aligned data: {save_comparison(rows, ref, cmp_, args.out_dir)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
