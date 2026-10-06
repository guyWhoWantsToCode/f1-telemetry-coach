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


# EventComparison.status values
MATCHED = "matched"  # one reference event <-> one comparison event
GROUPED = "grouped"  # one event on one lap <-> a nearby group of events on the other
AMBIGUOUS = "ambiguous"  # events overlap but cannot be paired confidently
REF_ONLY = "ref_only"
CMP_ONLY = "cmp_only"


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
    # Matching / reconciliation of events between the two laps
    match_radius_m: float = 150.0  # max distance between the minima of a one-to-one match
    min_overlap_fraction: float = 0.5  # range overlap (of the shorter event) for a confident link
    weak_overlap_fraction: float = 0.2  # overlap in [weak, min) makes the match ambiguous
    max_group_span_m: float = 300.0  # widest spread of minima allowed inside a grouped match
    extreme_brake_diff_m: float = 120.0  # larger brake/pickup shifts are treated as mismatches
    extreme_full_throttle_diff_m: float = 250.0  # same for the full-throttle point


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
    ref: Event  # None if only the comparison lap has this event (a merged Event for a group)
    cmp: Event  # None if only the reference lap has this event (a merged Event for a group)
    time_delta_ms: float  # comparison - reference through the event; None if unmatched
    status: str = MATCHED  # MATCHED, GROUPED, AMBIGUOUS, REF_ONLY or CMP_ONLY
    ref_events: tuple = ()  # the detected reference events behind `ref`
    cmp_events: tuple = ()  # the detected comparison events behind `cmp`
    note: str = ""  # why a match is ambiguous

    @property
    def comparable(self):
        """True when braking/throttle/speed differences are trustworthy."""
        return self.status in (MATCHED, GROUPED)

    def _diff(self, attr):
        if not self.comparable:
            return None
        a, b = getattr(self.ref, attr), getattr(self.cmp, attr)
        return None if a is None or b is None else b - a

    @property
    def brake_start_diff_m(self):
        return self._diff("brake_start_m")

    @property
    def min_speed_diff_kmh(self):
        return self._diff("min_speed_kmh")

    @property
    def pickup_diff_m(self):
        return self._diff("pickup_m")

    @property
    def full_throttle_diff_m(self):
        return self._diff("full_throttle_m")


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
            # Never before the event's last minimum, so the event's range always covers it.
            full = next((i for i in range(max(pickup, last), limit + 1)
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


def _range_overlap(a, b):
    """Fraction of the shorter event's distance range covered by the other (0 if disjoint)."""
    overlap = min(a.end_m, b.end_m) - max(a.start_m, b.start_m)
    if overlap <= 0:
        return 0.0
    return min(overlap / max(min(a.end_m - a.start_m, b.end_m - b.start_m), 1e-9), 1.0)


def _clusters(ref_events, cmp_events, th):
    """Group events from both laps whose distance ranges overlap.

    Strong links build the clusters: range overlap >= min_overlap_fraction, or a smaller
    overlap (>= weak_overlap_fraction) where one event's minimum-speed point lies inside
    the other event's range. A weak link
    (overlap between weak_overlap_fraction and min_overlap_fraction) joins the clusters it
    touches and marks the result ambiguous. Returns [(ref_indices, cmp_indices, weak)].
    """
    nodes = [("r", i) for i in range(len(ref_events))] + [("c", j) for j in range(len(cmp_events))]
    parent = {n: n for n in nodes}

    def find(n):
        while parent[n] != n:
            parent[n] = parent[parent[n]]
            n = parent[n]
        return n

    weak_pairs = []
    for i, r in enumerate(ref_events):
        for j, c in enumerate(cmp_events):
            frac = _range_overlap(r, c)
            core_inside = (c.start_m <= r.min_speed_m <= c.end_m) or (r.start_m <= c.min_speed_m <= r.end_m)
            if frac >= th.min_overlap_fraction or (core_inside and frac >= th.weak_overlap_fraction):
                parent[find(("r", i))] = find(("c", j))
            elif frac >= th.weak_overlap_fraction:
                weak_pairs.append((("r", i), ("c", j)))

    strong_roots = {n: find(n) for n in nodes}
    weak_roots = set()
    for a, b in weak_pairs:  # a weak link taints both clusters it touches
        weak_roots.update((strong_roots[a], strong_roots[b]))
        parent[find(a)] = find(b)

    clusters = {}
    for n in nodes:
        clusters.setdefault(find(n), []).append(n)
    out = []
    for members in clusters.values():
        weak = any(strong_roots[n] in weak_roots for n in members)
        out.append((sorted(i for k, i in members if k == "r"), sorted(j for k, j in members if k == "c"), weak))
    return out


def _combine(events):
    """One event representing a sequence of detected events (as detection would have merged)."""
    if len(events) == 1:
        return events[0]
    lowest = min(events, key=lambda e: e.min_speed_kmh)
    brakes = [e.brake_start_m for e in events if e.brake_start_m is not None]
    return Event(
        start_m=events[0].start_m, end_m=events[-1].end_m,
        min_speed_kmh=lowest.min_speed_kmh, min_speed_m=lowest.min_speed_m,
        brake_start_m=min(brakes) if brakes else None,
        peak_brake=max(e.peak_brake for e in events),
        pickup_m=events[-1].pickup_m, full_throttle_m=events[-1].full_throttle_m,
        start_idx=events[0].start_idx, end_idx=events[-1].end_idx,
    )


def _extreme(r, c, th):
    """Reason string if the braking/throttle shifts are too large to trust, else None."""
    for label, a, b, limit in (
        ("braking point", r.brake_start_m, c.brake_start_m, th.extreme_brake_diff_m),
        ("throttle pickup", r.pickup_m, c.pickup_m, th.extreme_brake_diff_m),
        ("full-throttle point", r.full_throttle_m, c.full_throttle_m, th.extreme_full_throttle_diff_m),
    ):
        if a is not None and b is not None and abs(b - a) > limit:
            return f"{label} differs by {abs(b - a):.0f} m, more than {limit:.0f} m"
    return None


def _classify(ref_group, cmp_group, weak, th):
    """(status, note) for one cluster of reference and comparison events."""
    if not ref_group:
        return CMP_ONLY, ""
    if not cmp_group:
        return REF_ONLY, ""
    plural = lambda n: f"{n} event" + ("s" if n != 1 else "")
    if weak:
        return AMBIGUOUS, "events only partly overlap their neighbours on the other lap"
    if len(ref_group) > 1 and len(cmp_group) > 1:
        return AMBIGUOUS, (f"{plural(len(ref_group))} on the reference lap overlap "
                           f"{plural(len(cmp_group))} on the comparison lap")
    r, c = _combine(ref_group), _combine(cmp_group)
    if len(ref_group) == len(cmp_group) == 1:
        if abs(r.min_speed_m - c.min_speed_m) > th.match_radius_m:
            return AMBIGUOUS, (f"minimum speeds are {abs(r.min_speed_m - c.min_speed_m):.0f} m apart "
                               "inside overlapping ranges")
        status = MATCHED
    else:
        group = ref_group if len(ref_group) > 1 else cmp_group
        spread = group[-1].min_speed_m - group[0].min_speed_m
        if spread > th.max_group_span_m:
            return AMBIGUOUS, f"grouped events span {spread:.0f} m, more than {th.max_group_span_m:.0f} m"
        status = GROUPED
    reason = _extreme(r, c, th)
    return (AMBIGUOUS, reason) if reason else (status, "")


def analyze(data, th=Thresholds()):
    """Detect events on both laps, reconcile them, and return a list of EventComparison.

    Events are paired by overlapping distance ranges (not by order): one event may match a
    nearby group of events on the other lap, and uncertain pairings are flagged AMBIGUOUS
    so no braking/throttle comparison is reported for them.
    """
    x, delta = data["distance_m"], data["delta_ms"]
    ref = detect_events(x, data["ref_speed_kmh"], data["ref_throttle"], data["ref_brake"], th)
    cmp_ = detect_events(x, data["cmp_speed_kmh"], data["cmp_throttle"], data["cmp_brake"], th)

    rows = []
    for ref_idx, cmp_idx, weak in _clusters(ref, cmp_, th):
        ref_group, cmp_group = [ref[i] for i in ref_idx], [cmp_[j] for j in cmp_idx]
        status, note = _classify(ref_group, cmp_group, weak, th)
        if status in (REF_ONLY, CMP_ONLY):  # unmatched events are listed one by one
            for ev in ref_group + cmp_group:
                rows.append((ev.min_speed_m, EventComparison(
                    "", ev.min_speed_m, ev if status == REF_ONLY else None,
                    ev if status == CMP_ONLY else None, None, status,
                    (ev,) if status == REF_ONLY else (), (ev,) if status == CMP_ONLY else ())))
            continue
        r, c = _combine(ref_group), _combine(cmp_group)
        first, last = min(r.start_idx, c.start_idx), max(r.end_idx, c.end_idx)
        rows.append((r.min_speed_m, EventComparison(
            "", r.min_speed_m, r, c, delta[last] - delta[first],  # time over the shared window
            status, tuple(ref_group), tuple(cmp_group), note)))
    rows.sort(key=lambda row: row[0])
    return [replace(ev, name=f"Event {n}") for n, (_, ev) in enumerate(rows, 1)]


# ---------------------------------------------------------------- reporting

def _num(value, fmt, hidden=False):
    return "?" if hidden else "-" if value is None else format(value, fmt)


def _events_text(events):
    return ", ".join(f"min {e.min_speed_kmh:.0f} km/h at {e.min_speed_m:.0f} m" for e in events)


def describe(ev):
    """Sentence-style differences for one event (comparison relative to reference)."""
    if ev.status == CMP_ONLY:
        return [f"only the comparison lap has an event here (min {ev.cmp.min_speed_kmh:.0f} km/h "
                f"at {ev.cmp.min_speed_m:.0f} m)"]
    if ev.status == REF_ONLY:
        return [f"only the reference lap has an event here (min {ev.ref.min_speed_kmh:.0f} km/h "
                f"at {ev.ref.min_speed_m:.0f} m)"]
    t = ev.time_delta_ms / 1000
    time_text = (f"{abs(t):.3f} s {'lost' if t > 0 else 'gained'} through the event"
                 if abs(t) >= 0.0005 else "no time difference through the event")
    if ev.status == AMBIGUOUS:
        return [f"AMBIGUOUS match ({ev.note}) - no braking/throttle comparison",
                f"reference: {_events_text(ev.ref_events)}",
                f"comparison: {_events_text(ev.cmp_events)}",
                f"{time_text.replace('the event', 'this section')} (measured by distance, still valid)"]
    lines = []
    if ev.status == GROUPED:
        lines.append(f"{len(ev.ref_events)} reference event(s) vs {len(ev.cmp_events)} comparison "
                     "event(s) treated as one sequence")
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
    lines.append(time_text)
    return lines


def format_table(results):
    cols = ["Event", "@ m", "Brake pt", "Peak brake %", "Min speed km/h", "Speed", "Pickup", "Full thr", "Time s"]
    sub = ["", "", "cmp-ref m", "ref / cmp", "ref / cmp", "cmp-ref", "cmp-ref m", "cmp-ref m", "cmp-ref"]
    rows = []
    for ev in results:
        r, c = ev.ref, ev.cmp
        amb = ev.status == AMBIGUOUS
        rows.append([
            ev.name, f"{ev.position_m:.0f}", _num(ev.brake_start_diff_m, "+.0f", amb),
            f"{_num(r and r.peak_brake * 100, '.0f')} / {_num(c and c.peak_brake * 100, '.0f')}",
            f"{_num(r and r.min_speed_kmh, '.0f')} / {_num(c and c.min_speed_kmh, '.0f')}",
            _num(ev.min_speed_diff_kmh, "+.1f", amb), _num(ev.pickup_diff_m, "+.0f", amb),
            _num(ev.full_throttle_diff_m, "+.0f", amb),
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
    if any(ev.status == AMBIGUOUS for ev in results):
        print("? = ambiguous match: events overlap but cannot be paired confidently, so no "
              "braking/throttle difference is shown (see Details)")
    print("\nDetails")
    for ev in results:
        print(f"  {ev.name} (~{ev.position_m:.0f} m): " + "; ".join(describe(ev)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
