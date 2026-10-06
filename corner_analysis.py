"""Detect braking/corner events in an aligned comparison CSV and compare the two laps.

    python corner_analysis.py data\\comparisons\\<comparison-file>.csv

Events are found independently on the reference and comparison laps (lap distance is the
axis), then matched by position. Everything is tuned through `Thresholds`.

How an event is detected on one lap
  * Candidate: a local speed minimum that stands at least `min_drop_kmh` below the
    surrounding speed on both sides (so tiny lifts and noise are ignored).
  * Merge: consecutive minima belonging to the same braking/corner sequence (the speed
    between them rises by < `merge_rise_kmh`, or they are < `merge_gap_m` apart) become
    one event, represented by its lowest minimum.
  * Start: the earliest of first brake input (>= `brake_on`) and first throttle lift
    (< `lift_throttle`) after the speed peak that precedes the minimum. Lift-only corners
    therefore work (brake start is reported as None).
  * Throttle pickup: first throttle >= `throttle_on` after the minimum. If throttle is
    already on at the minimum (overlap / trail braking), pickup is the start of that
    throttle run, but never earlier than the first minimum of the event.
  * Full throttle: first sustained (`full_hold_samples`) throttle >= `full_throttle`.
  * End: the full-throttle point, else the speed peak on the exit (capped by
    `max_exit_m` and by the next event's start).

Sign conventions (comparison minus reference):
  distance differences: negative = comparison earlier, positive = later
  speed differences:    positive = comparison faster
  time through event:   positive = comparison lost time, negative = comparison gained time
"""

import argparse
import csv
import sys
from dataclasses import dataclass, replace

from lap_compare import OUT_COLUMNS


class CornerError(Exception):
    """The comparison CSV cannot be analysed."""


@dataclass(frozen=True)
class Thresholds:
    min_drop_kmh: float = 20.0  # minimum speed drop for a real event (ignores small lifts)
    merge_rise_kmh: float = 25.0  # minima separated by a smaller rise are one sequence
    merge_gap_m: float = 75.0  # minima closer than this are one sequence
    brake_on: float = 0.10  # brake input counted as braking (0-1)
    lift_throttle: float = 0.90  # throttle below this counts as a lift
    throttle_on: float = 0.10  # throttle pickup threshold
    full_throttle: float = 0.98  # "full throttle" threshold
    full_hold_samples: int = 3  # samples full throttle must hold (3 x 5 m = 15 m)
    max_exit_m: float = 600.0  # longest exit searched for full throttle
    match_radius_m: float = 150.0  # max distance between matching events' minima


@dataclass(frozen=True)
class Event:
    start_m: float
    end_m: float
    min_speed_kmh: float
    min_speed_m: float
    brake_start_m: float  # None for lift-only events
    peak_brake: float  # 0-1 (0 if no braking)
    pickup_m: float  # None if throttle never picked up
    full_throttle_m: float  # None if full throttle never reached before the event ended
    start_idx: int
    end_idx: int


@dataclass(frozen=True)
class EventComparison:
    name: str
    position_m: float
    ref: Event  # None if only the comparison lap has this event
    cmp: Event  # None if only the reference lap has this event
    time_delta_ms: float  # comparison - reference through the event; None if unmatched

    @staticmethod
    def _diff(a, b):
        return None if a is None or b is None else b - a

    @property
    def brake_start_diff_m(self):
        return self._diff(self.ref and self.ref.brake_start_m, self.cmp and self.cmp.brake_start_m)

    @property
    def min_speed_diff_kmh(self):
        return self._diff(self.ref and self.ref.min_speed_kmh, self.cmp and self.cmp.min_speed_kmh)

    @property
    def pickup_diff_m(self):
        return self._diff(self.ref and self.ref.pickup_m, self.cmp and self.cmp.pickup_m)

    @property
    def full_throttle_diff_m(self):
        return self._diff(self.ref and self.ref.full_throttle_m, self.cmp and self.cmp.full_throttle_m)


def load_aligned(path):
    """Read an aligned comparison CSV into {column: [floats]}. Raises CornerError."""
    try:
        with open(path, newline="") as f:
            reader = csv.DictReader(f)
            missing = [c for c in OUT_COLUMNS if c not in (reader.fieldnames or [])]
            if missing:
                raise CornerError(f"{path}: not an aligned comparison CSV, missing columns {missing}")
            data = {c: [] for c in OUT_COLUMNS}
            for row in reader:
                for c in OUT_COLUMNS:
                    data[c].append(float(row[c]))
    except OSError as e:
        raise CornerError(f"cannot read {path}: {e}") from e
    except (ValueError, TypeError) as e:
        raise CornerError(f"{path}: bad or missing value in CSV ({e})") from e
    x = data["distance_m"]
    if len(x) < 3:
        raise CornerError(f"{path}: needs at least 3 rows")
    if any(b <= a for a, b in zip(x, x[1:])):
        raise CornerError(f"{path}: distance is not strictly increasing")
    return data


def _prominent_minima(v, min_drop):
    """Indices of local speed minima standing at least min_drop below both surroundings."""
    found = []
    for i in range(1, len(v) - 1):
        if not (v[i - 1] > v[i] <= v[i + 1]):
            continue
        left, j = v[i], i - 1
        while j >= 0 and v[j] >= v[i]:
            left, j = max(left, v[j]), j - 1
        right, j = v[i], i + 1
        while j < len(v) and v[j] >= v[i]:
            right, j = max(right, v[j]), j + 1
        if min(left, right) - v[i] >= min_drop:
            found.append(i)
    return found


def _merge_sequences(minima, v, x, th):
    groups = []
    for i in minima:
        if groups:
            last = groups[-1][-1]
            rise = max(v[last:i + 1]) - max(v[last], v[i])
            if rise < th.merge_rise_kmh or x[i] - x[last] < th.merge_gap_m:
                groups[-1].append(i)
                continue
        groups.append([i])
    return groups


def detect_events(x, speed, throttle, brake, th=Thresholds()):
    """Events on one lap, ordered by distance. All arrays share the same distance grid."""
    n = len(speed)
    groups = _merge_sequences(_prominent_minima(speed, th.min_drop_kmh), speed, x, th)

    # Pass 1: where each event starts (needs only the data up to its own minimum).
    prelim, prev_last = [], -1
    for g in groups:
        first, last = g[0], g[-1]
        lo = prev_last + 1
        peak = max(range(lo, first + 1), key=lambda i: (speed[i], i))  # last sample of the top
        brake_idx = next((i for i in range(peak, last + 1) if brake[i] >= th.brake_on), None)
        lift_idx = next((i for i in range(peak, first + 1) if throttle[i] < th.lift_throttle), None)
        starts = [i for i in (brake_idx, lift_idx) if i is not None]
        start = min(starts) if starts else peak
        low = min(g, key=lambda i: speed[i])
        prelim.append((first, last, low, start, brake_idx))
        prev_last = last

    # Pass 2: exit side, bounded by the next event's start.
    events = []
    for k, (first, last, low, start, brake_idx) in enumerate(prelim):
        next_start = prelim[k + 1][3] if k + 1 < len(prelim) else n
        limit = last
        while limit + 1 < min(next_start, n) and x[limit + 1] - x[last] <= th.max_exit_m:
            limit += 1

        if throttle[last] >= th.throttle_on:  # throttle already on at the minimum (overlap)
            pickup = last
            while pickup - 1 > first and throttle[pickup - 1] >= th.throttle_on:
                pickup -= 1
        else:
            pickup = next((i for i in range(last, limit + 1) if throttle[i] >= th.throttle_on), None)

        full = None
        if pickup is not None:
            hold = th.full_hold_samples
            full = next((i for i in range(pickup, limit + 1)
                         if i + hold <= n and all(t >= th.full_throttle for t in throttle[i:i + hold])), None)
        end = full if full is not None else max(range(last, limit + 1), key=lambda i: (speed[i], i))

        events.append(Event(
            start_m=x[start], end_m=x[end],
            min_speed_kmh=speed[low], min_speed_m=x[low],
            brake_start_m=x[brake_idx] if brake_idx is not None else None,
            peak_brake=max(brake[start:last + 1]) if brake_idx is not None else 0.0,
            pickup_m=x[pickup] if pickup is not None else None,
            full_throttle_m=x[full] if full is not None else None,
            start_idx=start, end_idx=end,
        ))
    return events


def _match(ref_events, cmp_events, radius):
    """Greedy nearest-first pairing of events by minimum-speed distance."""
    pairs = sorted(
        (abs(r.min_speed_m - c.min_speed_m), i, j)
        for i, r in enumerate(ref_events) for j, c in enumerate(cmp_events)
        if abs(r.min_speed_m - c.min_speed_m) <= radius
    )
    used_r, used_c, matched = set(), set(), {}
    for _, i, j in pairs:
        if i not in used_r and j not in used_c:
            used_r.add(i)
            used_c.add(j)
            matched[i] = j
    return matched


def analyze(data, th=Thresholds()):
    """Detect events on both laps, match them, and return a list of EventComparison."""
    x, delta = data["distance_m"], data["delta_ms"]
    ref = detect_events(x, data["ref_speed_kmh"], data["ref_throttle"], data["ref_brake"], th)
    cmp_ = detect_events(x, data["cmp_speed_kmh"], data["cmp_throttle"], data["cmp_brake"], th)
    matched = _match(ref, cmp_, th.match_radius_m)

    rows = []
    for i, r in enumerate(ref):
        if i in matched:
            c = cmp_[matched[i]]
            first, last = min(r.start_idx, c.start_idx), max(r.end_idx, c.end_idx)
            rows.append((r.min_speed_m, r, c, delta[last] - delta[first]))  # shared window
        else:
            rows.append((r.min_speed_m, r, None, None))
    matched_c = set(matched.values())
    rows += [(c.min_speed_m, None, c, None) for j, c in enumerate(cmp_) if j not in matched_c]
    rows.sort(key=lambda row: row[0])
    return [EventComparison(f"Event {n}", pos, r, c, t) for n, (pos, r, c, t) in enumerate(rows, 1)]


# ---------------------------------------------------------------- reporting

def _num(value, fmt):
    return "-" if value is None else format(value, fmt)


def describe(ev):
    """Sentence-style differences for one event (comparison relative to reference)."""
    if ev.ref is None:
        return [f"only the comparison lap has an event here (min {ev.cmp.min_speed_kmh:.0f} km/h "
                f"at {ev.cmp.min_speed_m:.0f} m)"]
    if ev.cmp is None:
        return [f"only the reference lap has an event here (min {ev.ref.min_speed_kmh:.0f} km/h "
                f"at {ev.ref.min_speed_m:.0f} m)"]
    lines = []
    d = ev.brake_start_diff_m
    if d is not None:
        lines.append("braked at the same point" if round(abs(d)) == 0
                     else f"braked {abs(d):.0f} m {'earlier' if d < 0 else 'later'}")
    elif (ev.ref.brake_start_m is None) != (ev.cmp.brake_start_m is None):
        lines.append("braked on only one lap (the other was a lift)")
    d = ev.min_speed_diff_kmh
    lines.append("same minimum speed" if round(abs(d), 1) == 0
                 else f"minimum speed {abs(d):.1f} km/h {'faster' if d > 0 else 'slower'}")
    for label, d in (("throttle pickup", ev.pickup_diff_m), ("full throttle", ev.full_throttle_diff_m)):
        if d is not None:
            lines.append(f"{label} at the same point" if round(abs(d)) == 0
                         else f"{label} {abs(d):.0f} m {'earlier' if d < 0 else 'later'}")
    t = ev.time_delta_ms / 1000
    lines.append(f"{abs(t):.3f} s {'lost' if t > 0 else 'gained'} through the event"
                 if abs(t) >= 0.0005 else "no time difference through the event")
    return lines


def format_table(results):
    cols = ["Event", "@ m", "Brake pt", "Peak brake %", "Min speed km/h", "Speed", "Pickup", "Full thr", "Time s"]
    sub = ["", "", "cmp-ref m", "ref / cmp", "ref / cmp", "cmp-ref", "cmp-ref m", "cmp-ref m", "cmp-ref"]
    rows = []
    for ev in results:
        r, c = ev.ref, ev.cmp
        rows.append([
            ev.name, f"{ev.position_m:.0f}", _num(ev.brake_start_diff_m, "+.0f"),
            f"{_num(r and r.peak_brake * 100, '.0f')} / {_num(c and c.peak_brake * 100, '.0f')}",
            f"{_num(r and r.min_speed_kmh, '.0f')} / {_num(c and c.min_speed_kmh, '.0f')}",
            _num(ev.min_speed_diff_kmh, "+.1f"), _num(ev.pickup_diff_m, "+.0f"),
            _num(ev.full_throttle_diff_m, "+.0f"),
            _num(None if ev.time_delta_ms is None else ev.time_delta_ms / 1000, "+.3f"),
        ])
    widths = [max(len(row[i]) for row in [cols, sub] + rows) for i in range(len(cols))]
    fmt = lambda row: "  ".join(cell.rjust(w) if i else cell.ljust(w)
                                for i, (cell, w) in enumerate(zip(row, widths)))
    rule = "-" * (sum(widths) + 2 * (len(widths) - 1))
    return "\n".join([fmt(cols), fmt(sub), rule] + [fmt(row) for row in rows])


def main(argv=None):
    ap = argparse.ArgumentParser(description="Detect and compare braking/corner events.")
    ap.add_argument("comparison_csv", help="CSV from lap_compare.py (in data/comparisons/)")
    d = Thresholds()
    ap.add_argument("--min-drop", type=float, default=d.min_drop_kmh,
                    help=f"minimum speed drop in km/h for an event (default {d.min_drop_kmh:g})")
    ap.add_argument("--merge-rise", type=float, default=d.merge_rise_kmh,
                    help=f"minima separated by a smaller rise merge (default {d.merge_rise_kmh:g})")
    ap.add_argument("--brake-on", type=float, default=d.brake_on,
                    help=f"brake input counted as braking, 0-1 (default {d.brake_on:g})")
    args = ap.parse_args(argv)
    th = replace(d, min_drop_kmh=args.min_drop, merge_rise_kmh=args.merge_rise, brake_on=args.brake_on)

    try:
        results = analyze(load_aligned(args.comparison_csv), th)
    except CornerError as e:
        print(f"Error: {e}")
        return 1

    if not results:
        print("No braking/corner events detected (try a smaller --min-drop).")
        return 0
    print(f"Detected {len(results)} events (differences are comparison minus reference; "
          "Time: + = comparison lost time)\n")
    print(format_table(results))
    print("\nDetails")
    for ev in results:
        print(f"  {ev.name} (~{ev.position_m:.0f} m): " + "; ".join(describe(ev)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
