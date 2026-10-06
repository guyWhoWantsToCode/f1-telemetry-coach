import contextlib
import csv
import io
import tempfile
import unittest
from pathlib import Path

from corner_analysis import (
    AMBIGUOUS, CMP_ONLY, GROUPED, MATCHED, REF_ONLY, CornerError, Event, Thresholds, _classify,
    _clusters, analyze, describe, detect_events, format_table, load_aligned, main,
)
from lap_compare import OUT_COLUMNS

STEP = 5.0
X = [i * STEP for i in range(0, 601)]  # 0 .. 3000 m


def piecewise(points):
    """Function of distance, linearly interpolating between (distance, value) points."""
    def f(d):
        if d <= points[0][0]:
            return points[0][1]
        for (x0, y0), (x1, y1) in zip(points, points[1:]):
            if d <= x1:
                return y0 + (y1 - y0) * (d - x0) / (x1 - x0)
        return points[-1][1]
    return f


def corner(brake_at, min_at, min_speed, exit_to=300.0, top=300.0, pickup_ramp=40.0):
    """Speed/brake/throttle functions for one braking zone and corner exit."""
    exit_end = min_at + 100
    speed = [(brake_at, top), (min_at, min_speed), (exit_end, exit_to)]
    brake = [(brake_at - 0.1, 0), (brake_at, 1.0), (min_at, 1.0), (min_at + 0.1, 0)]
    throttle = [(brake_at - 10, 1.0), (brake_at - 9.9, 0.0), (min_at, 0.0), (min_at + pickup_ramp, 1.0)]
    return speed, brake, throttle


def build_lap(corners):
    """Telemetry arrays for a lap of straights (300 km/h) plus the given corners."""
    speed_pts, brake_fns, throttle_fns = [(0.0, 300.0)], [], []
    for s, b, t in corners:
        speed_pts += s
        brake_fns.append(piecewise(b))
        throttle_fns.append(piecewise(t))
    speed_pts.append((3000.0, 300.0))
    sp = piecewise(speed_pts)
    speed = [sp(d) for d in X]
    brake = [max([f(d) for f in brake_fns] + [0.0]) for d in X]
    throttle = [1.0] * len(X)
    for _, _, t in corners:  # each corner's throttle curve applies only inside its own range
        f = piecewise(t)
        throttle = [min(a, f(d)) if t[0][0] - 1 <= d <= t[-1][0] else a
                    for a, d in zip(throttle, X)]
    return speed, brake, throttle


def times_ms(speed):
    """Cumulative time at each grid distance for the given speeds (km/h)."""
    out, t = [0.0], 0.0
    for v0, v1 in zip(speed, speed[1:]):
        t += STEP / ((v0 + v1) / 2 / 3.6) * 1000
        out.append(t)
    return out


def aligned(ref, cmp_):
    """An aligned-comparison dict (what load_aligned returns) from two telemetry triples."""
    rt, ct = times_ms(ref[0]), times_ms(cmp_[0])
    return {
        "distance_m": X, "ref_time_ms": rt, "cmp_time_ms": ct,
        "delta_ms": [c - r for r, c in zip(rt, ct)],
        "ref_speed_kmh": ref[0], "cmp_speed_kmh": cmp_[0],
        "ref_brake": ref[1], "cmp_brake": cmp_[1],
        "ref_throttle": ref[2], "cmp_throttle": cmp_[2],
        "ref_steer": [0.0] * len(X), "cmp_steer": [0.0] * len(X),
        "ref_gear": [4] * len(X), "cmp_gear": [4] * len(X),
    }


def detect(lap, th=Thresholds()):
    return detect_events(X, lap[0], lap[2], lap[1], th)


class DetectEventsTests(unittest.TestCase):
    def test_single_corner_known_values(self):
        lap = build_lap([corner(brake_at=500, min_at=600, min_speed=100)])
        events = detect(lap)
        self.assertEqual(len(events), 1)
        e = events[0]
        self.assertEqual(e.brake_start_m, 500.0)
        self.assertEqual(e.peak_brake, 1.0)
        self.assertEqual(e.min_speed_m, 600.0)
        self.assertAlmostEqual(e.min_speed_kmh, 100.0)
        self.assertAlmostEqual(e.pickup_m, 605.0, delta=5)  # throttle >= 10% just after the minimum
        self.assertAlmostEqual(e.full_throttle_m, 640.0, delta=5)
        self.assertLessEqual(e.start_m, 500.0)
        self.assertAlmostEqual(e.end_m, 640.0, delta=5)

    def test_two_separate_corners(self):
        lap = build_lap([corner(500, 600, 100), corner(1500, 1600, 120)])
        events = detect(lap)
        self.assertEqual([e.min_speed_m for e in events], [600.0, 1600.0])
        self.assertEqual(events[1].brake_start_m, 1500.0)

    def test_tiny_lift_and_noise_are_ignored(self):
        lap = build_lap([corner(500, 600, 285, top=300.0, exit_to=300.0)])  # 15 km/h dip
        self.assertEqual(detect(lap), [])
        noisy = list(lap[0])
        for i in range(0, len(noisy), 2):
            noisy[i] -= 3  # +/-3 km/h zig-zag everywhere
        self.assertEqual(detect((noisy, lap[1], lap[2])), [])

    def test_nearby_minima_merge_into_one_sequence(self):
        # Two minima 60 m apart with a small bump between them: one braking sequence.
        speed = piecewise([(0, 300), (500, 300), (580, 90), (610, 130), (640, 95), (760, 300), (3000, 300)])
        brake = piecewise([(499, 0), (500, 1), (640, 1), (641, 0)])
        lap = ([speed(d) for d in X], [brake(d) for d in X], [0.0 if 490 <= d <= 650 else 1.0 for d in X])
        events = detect(lap)
        self.assertEqual(len(events), 1)
        self.assertAlmostEqual(events[0].min_speed_kmh, 90.0, delta=1)
        self.assertEqual(events[0].brake_start_m, 500.0)

    def test_distant_minima_stay_separate_even_with_modest_bump(self):
        speed = piecewise([(0, 300), (500, 300), (580, 90), (700, 180), (790, 95), (900, 300), (3000, 300)])
        brake = piecewise([(499, 0), (500, 1), (580, 1), (581, 0), (699, 0), (700, 1), (790, 1), (791, 0)])
        lap = ([speed(d) for d in X], [brake(d) for d in X], [1.0] * len(X))
        self.assertEqual(len(detect(lap)), 2)  # 90 km/h rise between them, 210 m apart

    def test_lift_only_corner_without_braking(self):
        speed = piecewise([(0, 300), (500, 300), (560, 250), (600, 240), (700, 300), (3000, 300)])
        throttle = piecewise([(0, 1), (500, 1), (501, 0.4), (600, 0.4), (640, 1), (3000, 1)])
        lap = ([speed(d) for d in X], [0.0] * len(X), [throttle(d) for d in X])
        events = detect(lap)
        self.assertEqual(len(events), 1)
        e = events[0]
        self.assertIsNone(e.brake_start_m)
        self.assertEqual(e.peak_brake, 0.0)
        self.assertAlmostEqual(e.min_speed_kmh, 240.0, delta=1)
        self.assertAlmostEqual(e.start_m, 505.0, delta=5)  # starts at the throttle lift

    def test_braking_and_throttle_overlap(self):
        # Throttle is already 30% while still braking through the minimum.
        speed = piecewise([(500, 300), (600, 100), (700, 300)])
        brake = piecewise([(499, 0), (500, 1), (610, 0.5), (611, 0)])
        throttle = piecewise([(0, 1), (500, 1), (501, 0), (560, 0.3), (700, 1)])
        lap = ([speed(d) if 500 <= d <= 700 else 300.0 for d in X], [brake(d) for d in X],
               [throttle(d) for d in X])
        e = detect(lap)[0]
        self.assertEqual(e.brake_start_m, 500.0)
        self.assertLessEqual(e.pickup_m, e.min_speed_m)  # throttle was on before the minimum
        self.assertGreaterEqual(e.pickup_m, 560.0 - 5)
        self.assertIsNotNone(e.full_throttle_m)

    def test_thresholds_are_configurable(self):
        lap = build_lap([corner(500, 600, 285)])
        self.assertEqual(len(detect(lap, Thresholds(min_drop_kmh=10.0))), 1)

    def test_no_full_throttle_before_next_event(self):
        # Exit never reaches full throttle: ends at the speed peak, full throttle None.
        speed, brake, _ = corner(500, 600, 100)
        throttle = [piecewise([(0, 1), (500, 1), (501, 0), (600, 0), (700, 0.6), (900, 0.6)])(d) for d in X]
        lap = ([piecewise([(0, 300)] + speed + [(3000, 300)])(d) for d in X],
               [piecewise(brake)(d) for d in X], throttle)
        e = detect(lap)[0]
        self.assertIsNone(e.full_throttle_m)
        self.assertIsNotNone(e.pickup_m)


class AnalyzeTests(unittest.TestCase):
    def test_matched_event_differences(self):
        ref = build_lap([corner(500, 600, 100)])
        cmp_ = build_lap([corner(520, 620, 105)])  # brakes 20 m later, 5 km/h faster minimum
        (ev,) = analyze(aligned(ref, cmp_))
        self.assertEqual(ev.name, "Event 1")
        self.assertEqual(ev.brake_start_diff_m, 20.0)
        self.assertAlmostEqual(ev.min_speed_diff_kmh, 5.0)
        self.assertEqual(ev.pickup_diff_m, 20.0)
        self.assertEqual(ev.full_throttle_diff_m, 20.0)
        text = " ".join(describe(ev))
        self.assertIn("braked 20 m later", text)
        self.assertIn("5.0 km/h faster", text)

    def test_time_through_event_matches_aligned_delta(self):
        ref = build_lap([corner(500, 600, 100)])
        cmp_ = build_lap([corner(500, 600, 70)])  # much slower minimum
        data = aligned(ref, cmp_)
        (ev,) = analyze(data)
        self.assertGreater(ev.time_delta_ms, 0)  # positive = comparison lost time
        first = min(ev.ref.start_idx, ev.cmp.start_idx)
        last = max(ev.ref.end_idx, ev.cmp.end_idx)
        self.assertAlmostEqual(ev.time_delta_ms, data["delta_ms"][last] - data["delta_ms"][first])
        self.assertIn("lost through the event", " ".join(describe(ev)))

    def test_faster_comparison_gains_time(self):
        ref = build_lap([corner(500, 600, 70)])
        cmp_ = build_lap([corner(500, 600, 100)])
        (ev,) = analyze(aligned(ref, cmp_))
        self.assertLess(ev.time_delta_ms, 0)
        self.assertIn("gained through the event", " ".join(describe(ev)))

    def test_unmatched_events_and_ordering(self):
        ref = build_lap([corner(500, 600, 100), corner(1500, 1600, 120)])
        cmp_ = build_lap([corner(500, 600, 100), corner(2000, 2100, 90)])  # different place
        results = analyze(aligned(ref, cmp_))
        self.assertEqual([r.name for r in results], ["Event 1", "Event 2", "Event 3"])
        self.assertEqual([r.position_m for r in results], [600.0, 1600.0, 2100.0])
        self.assertIsNotNone(results[0].ref and results[0].cmp)
        self.assertIsNone(results[1].cmp)  # reference only
        self.assertIsNone(results[2].ref)  # comparison only
        self.assertIsNone(results[1].time_delta_ms)
        self.assertIn("only the reference lap", describe(results[1])[0])
        self.assertIn("only the comparison lap", describe(results[2])[0])

    def test_lift_vs_brake_reported_not_crashing(self):
        ref = build_lap([corner(500, 600, 100)])
        speed = piecewise([(0, 300), (500, 300), (600, 110), (700, 300), (3000, 300)])
        throttle = piecewise([(0, 1), (500, 1), (501, 0), (600, 0), (640, 1)])
        cmp_ = ([speed(d) for d in X], [0.0] * len(X), [throttle(d) for d in X])
        (ev,) = analyze(aligned(ref, cmp_))
        self.assertIsNone(ev.brake_start_diff_m)
        self.assertIn("braked on only one lap", " ".join(describe(ev)))


def lap_from(speed_points, brake_zones, throttle_curves):
    """Telemetry arrays: speed from points, brake=1 inside zones, throttle 0 from `off` to
    `pickup`, then a linear ramp to 1 at `full` (throttle is 1 everywhere else)."""
    sp = piecewise([(0.0, 300.0)] + speed_points + [(3000.0, 300.0)])
    speed = [sp(d) for d in X]
    brake = [1.0 if any(a <= d <= b for a, b in brake_zones) else 0.0 for d in X]
    throttle = []
    for d in X:
        value = 1.0
        for off, pickup, full in throttle_curves:
            if off <= d < pickup:
                value = 0.0
            elif pickup <= d < full:
                value = (d - pickup) / (full - pickup)
        throttle.append(value)
    return speed, brake, throttle


def two_event_lap(a_brake=500, b_brake=655, a_min=90, b_min=95):
    """Two corners 140 m apart; the speed recovers 55 km/h between the minima, so detection
    reports TWO events (minima at 580 m and 720 m)."""
    return lap_from(
        [(500, 300), (580, a_min), (650, 150), (720, b_min), (860, 300)],
        [(a_brake, 580), (b_brake, 720)], [(495, 580, 620), (650, 720, 760)])


def one_event_lap(min_speed=95):
    """The same section driven as one sequence: tiny recovery between the minima, so
    detection merges it into ONE event (minimum at 580 m)."""
    return lap_from(
        [(500, 300), (580, min_speed), (650, 110), (720, 100), (860, 300)],
        [(500, 720)], [(495, 720, 760)])


def ev(start, end, min_m, min_kmh=100.0, brake=None, pickup=None, full=None):
    return Event(start_m=start, end_m=end, min_speed_kmh=min_kmh, min_speed_m=min_m,
                 brake_start_m=brake, peak_brake=1.0 if brake is not None else 0.0,
                 pickup_m=pickup, full_throttle_m=full,
                 start_idx=int(start / STEP), end_idx=int(end / STEP))


class ReconciliationTests(unittest.TestCase):
    def test_fixture_laps_detect_as_intended(self):
        self.assertEqual(len(detect(two_event_lap())), 2)
        self.assertEqual(len(detect(one_event_lap())), 1)

    def test_one_event_vs_one_event(self):
        (r,) = analyze(aligned(one_event_lap(), one_event_lap(min_speed=90)))
        self.assertEqual(r.status, MATCHED)
        self.assertAlmostEqual(r.min_speed_diff_kmh, -5.0)
        self.assertEqual(r.brake_start_diff_m, 0.0)
        self.assertEqual((len(r.ref_events), len(r.cmp_events)), (1, 1))

    def test_two_reference_events_vs_one_comparison_event(self):
        data = aligned(two_event_lap(), one_event_lap())
        (r,) = analyze(data)
        self.assertEqual(r.status, GROUPED)
        self.assertEqual((len(r.ref_events), len(r.cmp_events)), (2, 1))
        self.assertEqual(r.brake_start_diff_m, 0.0)  # earliest braking of the group vs the single event
        self.assertEqual(r.pickup_diff_m, 0.0)  # exit of the LAST reference event vs the exit
        self.assertEqual(r.full_throttle_diff_m, 0.0)
        self.assertAlmostEqual(r.min_speed_diff_kmh, 5.0)  # lowest minima: 90 vs 95
        first = min(r.ref.start_idx, r.cmp.start_idx)
        last = max(r.ref.end_idx, r.cmp.end_idx)
        self.assertAlmostEqual(r.time_delta_ms, data["delta_ms"][last] - data["delta_ms"][first])
        self.assertIn("treated as one sequence", " ".join(describe(r)))

    def test_one_reference_event_vs_two_comparison_events(self):
        (r,) = analyze(aligned(one_event_lap(), two_event_lap()))
        self.assertEqual(r.status, GROUPED)
        self.assertEqual((len(r.ref_events), len(r.cmp_events)), (1, 2))
        self.assertEqual(r.brake_start_diff_m, 0.0)
        self.assertAlmostEqual(r.min_speed_diff_kmh, -5.0)

    def test_nearby_but_genuinely_separate_corners_stay_separate(self):
        ref = two_event_lap()
        cmp_ = two_event_lap(a_brake=510, b_brake=675)  # brakes 10 m and 20 m later
        a, b = analyze(aligned(ref, cmp_))
        self.assertEqual((a.status, b.status), (MATCHED, MATCHED))
        self.assertEqual((a.brake_start_diff_m, b.brake_start_diff_m), (10.0, 20.0))
        self.assertEqual((a.name, b.name), ("Event 1", "Event 2"))

    def test_extreme_brake_difference_is_ambiguous_not_reported(self):
        ref = build_lap([corner(500, 600, 100)])
        cmp_ = build_lap([corner(340, 600, 100)])  # same corner, braking 160 m earlier
        (r,) = analyze(aligned(ref, cmp_))
        self.assertEqual(r.status, AMBIGUOUS)
        self.assertIn("braking point differs by 160 m", r.note)
        self.assertIsNone(r.brake_start_diff_m)
        self.assertIsNone(r.pickup_diff_m)
        self.assertIsNotNone(r.time_delta_ms)  # time over the section is still measured by distance
        text = " ".join(describe(r))
        self.assertIn("AMBIGUOUS", text)
        self.assertNotIn("braked", text)
        self.assertIn("?", format_table([r]))

    def test_unmatched_events_stay_unmatched(self):
        results = analyze(aligned(build_lap([corner(500, 600, 100)]), build_lap([corner(1500, 1600, 100)])))
        self.assertEqual([r.status for r in results], [REF_ONLY, CMP_ONLY])
        self.assertTrue(all(not r.comparable for r in results))

    # --- the clustering/classification rules on hand-built events
    def test_clusters_one_to_one_and_separate_pairs(self):
        ref = [ev(500, 620, 580), ev(655, 760, 720)]
        cmp_ = [ev(505, 625, 582), ev(660, 765, 722)]
        clusters = _clusters(ref, cmp_, Thresholds())
        self.assertEqual(sorted(clusters), [([0], [0], False), ([1], [1], False)])

    def test_two_to_two_overlap_is_ambiguous(self):
        # Each comparison event spans parts of both reference events: no clean pairing.
        ref = [ev(500, 640, 580), ev(600, 760, 720)]
        cmp_ = [ev(520, 660, 600), ev(620, 780, 700)]
        ((r_idx, c_idx, weak),) = _clusters(ref, cmp_, Thresholds())
        self.assertEqual((r_idx, c_idx), ([0, 1], [0, 1]))
        status, note = _classify([ref[i] for i in r_idx], [cmp_[i] for i in c_idx], weak, Thresholds())
        self.assertEqual(status, AMBIGUOUS)
        self.assertIn("2 events on the reference lap overlap 2 events", note)

    def test_partial_overlap_is_ambiguous(self):
        ref = [ev(500, 620, 580)]
        cmp_ = [ev(585, 700, 650)]  # overlaps ~30% of the shorter event: neither same nor different
        ((_, _, weak),) = _clusters(ref, cmp_, Thresholds())
        self.assertTrue(weak)
        self.assertEqual(_classify(ref, cmp_, weak, Thresholds())[0], AMBIGUOUS)

    def test_far_apart_minima_inside_overlapping_ranges_are_ambiguous(self):
        ref, cmp_ = [ev(500, 900, 560)], [ev(500, 900, 800)]
        ((_, _, weak),) = _clusters(ref, cmp_, Thresholds())
        status, note = _classify(ref, cmp_, weak, Thresholds())
        self.assertEqual(status, AMBIGUOUS)
        self.assertIn("240 m apart", note)

    def test_group_spread_limit(self):
        wide = [ev(500, 620, 560), ev(640, 1000, 900)]  # minima 340 m apart
        single = [ev(500, 1000, 560)]
        ((_, _, weak),) = _clusters(wide, single, Thresholds())
        self.assertEqual(_classify(wide, single, weak, Thresholds())[0], AMBIGUOUS)
        self.assertEqual(_classify(wide, single, weak, Thresholds(max_group_span_m=400.0))[0], GROUPED)


class LoadAndCliTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def write(self, data, name="cmp.csv"):
        path = self.dir / name
        with open(path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(OUT_COLUMNS)
            for i in range(len(data["distance_m"])):
                w.writerow([data[c][i] for c in OUT_COLUMNS])
        return path

    def test_cli_prints_table_and_details(self):
        ref = build_lap([corner(500, 600, 100)])
        cmp_ = build_lap([corner(520, 620, 105)])
        path = self.write(aligned(ref, cmp_))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = main([str(path)])
        text = buf.getvalue()
        self.assertEqual(code, 0)
        self.assertIn("Detected 1 events", text)
        self.assertIn("Event 1", text)
        self.assertIn("braked 20 m later", text)

    def test_cli_option_changes_detection(self):
        ref = build_lap([corner(500, 600, 285)])
        path = self.write(aligned(ref, ref))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            main([str(path)])
            main([str(path), "--min-drop", "10"])
        self.assertIn("No braking/corner events detected", buf.getvalue())
        self.assertIn("Detected 1 events", buf.getvalue())

    def test_bad_input(self):
        with self.assertRaises(CornerError):
            load_aligned(self.dir / "missing.csv")
        wrong = self.dir / "wrong.csv"
        wrong.write_text("a,b\n1,2\n")
        with self.assertRaises(CornerError):
            load_aligned(wrong)
        short = self.dir / "short.csv"
        short.write_text(",".join(OUT_COLUMNS) + "\n")
        with self.assertRaises(CornerError):
            load_aligned(short)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(main([str(wrong)]), 1)
        self.assertIn("Error", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
