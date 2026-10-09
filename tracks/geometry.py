"""Building a persistent circuit trace from recorded world positions. Pure functions, no files.

What the result is, and is not
  * `driver_path` is the DRIVER'S path: the pointwise median of several valid, complete laps.
    It is a racing line, not the track. The track centerline is explicitly marked unavailable:
    it cannot be derived from where one driver chose to drive.
  * Laps are only combined when they agree with each other geometrically. A lap whose path,
    length or layout does not match is rejected and reported, so coordinates of unrelated
    circuits, sessions or layouts are never merged.

Coordinates and orientation
  The Motion packet gives world X/Y/Z in metres and the spec does not say which axis is up.
  The vertical axis is therefore checked from the data (it should have by far the smallest
  extent), and the map is drawn in the X/Z plane with the aspect ratio preserved. Whether the
  plane is mirrored is decided from the driver's own steering: right turns (steer > 0) must
  turn clockwise as seen from above; if the X/Z plane gives the opposite, Z is flipped.
"""

import math
import statistics
from bisect import bisect_right
from dataclasses import dataclass

from tracks.positions import LapPath


@dataclass(frozen=True)
class GeometryConfig:
    step_m: float = 5.0  # spacing of the stored path
    min_coverage: float = 0.95  # a lap must cover this fraction of the circuit length
    max_start_m: float = 100.0  # ... starting this close to the line
    max_gap_m: float = 40.0  # ... with no hole in the positions longer than this
    max_length_error: float = 0.01  # a lap declaring a different circuit length is rejected
    max_deviation_m: float = 40.0  # median distance to the consensus path allowed
    closure_limit_m: float = 50.0  # start and end of a lap trace must be this close to be "closed"
    vertical_ratio: float = 0.2  # the vertical axis must span less than this fraction of the others
    min_orientation_r: float = 0.3  # |correlation| of steering with turning needed to trust the mirror
    max_laps: int = 30  # most recent laps considered


@dataclass(frozen=True)
class LapInput:
    lap_id: str
    path: LapPath
    steer_distance: tuple = ()  # the lap's own steering samples (distance, -1 left .. +1 right)
    steer: tuple = ()
    declared_length_m: float = None  # the circuit length the game reported when it was recorded


def interpolate(distances, values, d):
    """Linear interpolation of `values` at distance d; d must lie inside the recorded range."""
    if d < distances[0] - 1e-9 or d > distances[-1] + 1e-9:
        raise ValueError("distance outside the recorded range")
    i = bisect_right(distances, d)
    if i >= len(distances):
        return values[-1]
    if i == 0:
        return values[0]
    d0, d1 = distances[i - 1], distances[i]
    return values[i - 1] + (values[i] - values[i - 1]) * (d - d0) / (d1 - d0)


def resample(path, grid):
    """The path at the given distances (all must lie inside the recorded range)."""
    return [[interpolate(path.distance, axis, d) for d in grid] for axis in (path.x, path.y, path.z)]


def _grid(lo, hi, step):
    first = math.ceil(lo / step - 1e-9)
    last = math.floor(hi / step + 1e-9)
    return [round(k * step, 6) for k in range(first, last + 1)]


def check_lap(lap, reference_length, cfg):
    """Why a lap cannot be used to build the circuit trace, or None if it can."""
    d = lap.path.distance
    span = d[-1] - d[0]
    if d[0] > cfg.max_start_m:
        return f"does not start at the line (first position at {d[0]:.0f} m)"
    if reference_length and span < cfg.min_coverage * reference_length:
        return f"incomplete lap ({span:.0f} m of {reference_length:.0f} m)"
    if max(b - a for a, b in zip(d, d[1:])) > cfg.max_gap_m:
        return "gaps in the recorded positions"
    if lap.declared_length_m and reference_length and \
            abs(lap.declared_length_m - reference_length) / reference_length > cfg.max_length_error:
        return f"recorded on a circuit length of {lap.declared_length_m:.0f} m, not {reference_length:.0f} m"
    return None


def _median_deviation(a, b):
    """Median horizontal (X/Z) distance between two paths sampled on the same grid."""
    return statistics.median(math.hypot(ax - bx, az - bz) for ax, bx, az, bz in zip(a[0], b[0], a[2], b[2]))


def orientation(grid, xs, zs, steer_distance, steer):
    """Correlation between the driver's steering and the path's turning, in the X/Z plane.

    Positive means right turns (steer > 0) turn clockwise when X is drawn right and Z down, so
    Z can be used as drawn. Negative means Z has to be flipped. Returns None without steering.
    """
    if len(steer_distance) < 2:
        return None
    heading = [math.atan2(zs[i + 1] - zs[i], xs[i + 1] - xs[i]) for i in range(len(xs) - 1)]
    sxy = sxx = syy = 0.0
    for i in range(len(heading) - 1):
        turn = (heading[i + 1] - heading[i] + math.pi) % (2 * math.pi) - math.pi
        d = grid[i + 1]
        if not steer_distance[0] <= d <= steer_distance[-1] or abs(turn) > math.pi / 2:
            continue
        s = interpolate(steer_distance, steer, d)
        sxy += s * turn
        sxx += s * s
        syy += turn * turn
    if sxx == 0 or syy == 0:
        return None
    return sxy / math.sqrt(sxx * syy)


def axes_report(xs, ys, zs, cfg):
    spans = {"x": max(xs) - min(xs), "y": max(ys) - min(ys), "z": max(zs) - min(zs)}
    vertical = min(spans, key=spans.get)
    others = [v for k, v in spans.items() if k != vertical]
    verified = vertical == "y" and spans["y"] < cfg.vertical_ratio * min(others)
    return {"spans_m": {k: round(v, 1) for k, v in spans.items()},
            "vertical_axis": vertical, "vertical_axis_verified": bool(verified)}


def _polyline_length(xs, ys, zs):
    return sum(math.dist((xs[i], ys[i], zs[i]), (xs[i + 1], ys[i + 1], zs[i + 1])) for i in range(len(xs) - 1))


def build_geometry(laps, track_length_m=None, cfg=GeometryConfig()):
    """Combine valid laps into one driver-path trace. Returns a dict (see the module docstring),
    or None when no lap qualifies. `laps` are LapInput for valid laps of ONE circuit."""
    laps = list(laps)[-cfg.max_laps:]
    declared = [l.declared_length_m for l in laps if l.declared_length_m]
    reference = (statistics.median(declared) if declared else None) or track_length_m
    if not reference:
        spans = [l.path.distance[-1] - l.path.distance[0] for l in laps]
        reference = statistics.median(spans) if spans else None

    rejected, usable = [], []
    for lap in laps:
        reason = check_lap(lap, reference, cfg)
        (rejected.append({"lap_id": lap.lap_id, "reason": reason}) if reason else usable.append(lap))
    if not usable:
        return {"laps": [], "rejected": rejected, "driver_path": None}

    grid = _grid(max(l.path.distance[0] for l in usable), min(l.path.distance[-1] for l in usable), cfg.step_m)
    paths = {l.lap_id: resample(l.path, grid) for l in usable}

    # Consensus: the lap closest to the others, then keep the laps that agree with it.
    if len(usable) == 1:
        accepted, cross_checked = usable, False
    else:
        score = {a.lap_id: statistics.median(_median_deviation(paths[a.lap_id], paths[b.lap_id])
                                             for b in usable if b is not a) for a in usable}
        medoid = min(usable, key=lambda l: score[l.lap_id])
        accepted = []
        for lap in usable:
            dev = 0.0 if lap is medoid else _median_deviation(paths[lap.lap_id], paths[medoid.lap_id])
            if dev <= cfg.max_deviation_m:
                accepted.append(lap)
            else:
                rejected.append({"lap_id": lap.lap_id,
                                 "reason": f"path does not match the other laps (median deviation {dev:.0f} m)"})
        cross_checked = len(accepted) > 1

    median_path = [[statistics.median(paths[l.lap_id][axis][i] for l in accepted) for i in range(len(grid))]
                   for axis in range(3)]
    xs, ys, zs = median_path
    deviations = [statistics.median(math.hypot(paths[l.lap_id][0][i] - xs[i], paths[l.lap_id][2][i] - zs[i])
                                    for l in accepted) for i in range(len(grid))]

    # Orientation from every accepted lap's own steering (pooled).
    rs = []
    for lap in accepted:
        r = orientation(grid, paths[lap.lap_id][0], paths[lap.lap_id][2], lap.steer_distance, lap.steer)
        if r is not None:
            rs.append(r)
    r = statistics.mean(rs) if rs else None
    closure = math.dist((xs[0], zs[0]), (xs[-1], zs[-1]))
    length = _polyline_length(xs, ys, zs)
    ref_len = track_length_m or reference
    return {
        "laps": [l.lap_id for l in accepted],
        "rejected": rejected,
        "driver_path": {
            "step_m": cfg.step_m,
            "distance_m": [round(d, 1) for d in grid],
            "x": [round(v, 2) for v in xs], "y": [round(v, 2) for v in ys], "z": [round(v, 2) for v in zs],
        },
        "quality": {
            "lap_count": len(accepted),
            "cross_checked": cross_checked,
            "spread_m": round(statistics.median(deviations), 2),
            "max_spread_m": round(max(deviations), 2),
            "closure_gap_m": round(closure, 1),
            "closed": closure <= cfg.closure_limit_m,
            "path_length_m": round(length, 1),
            "length_ratio": round(length / ref_len, 3) if ref_len else None,
        },
        "axes": axes_report(xs, ys, zs, cfg),
        "orientation": {
            "mirror_z": bool(r is not None and r < 0),
            "r": round(r, 3) if r is not None else None,
            "verified": bool(r is not None and abs(r) >= cfg.min_orientation_r),
            "laps_checked": len(rs),
        },
    }
