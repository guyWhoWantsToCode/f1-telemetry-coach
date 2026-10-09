"""Tests for mapping generic detected events to real corners (tracks/corners.py).

The mapper is exercised both directly and end to end through the existing, track-agnostic
event detector and matcher (corner_analysis.analyze) on synthetic laps.
"""

import unittest

from corner_analysis import analyze
from test_corner_analysis import aligned, build_lap, corner, lap_from
from tracks.corners import COMPLEX, SINGLE, UNCERTAIN, UNKNOWN, map_comparison_events, map_event, map_point
from tracks.metadata import parse_track_metadata


def circuit(corners, complexes=()):
    return parse_track_metadata({
        "track_id": 9990, "name": "Test Circuit",
        "corners": [{"number": n, "range_m": rng} for n, rng in corners],
        "complexes": [{"corners": list(c)} for c in complexes],
    })


# T1 and T2 are separate corners; T3-T6 is a declared complex; T7 stands alone.
TEST_CIRCUIT = circuit(
    [(1, [560, 680]), (2, [1560, 1640]), (3, [2000, 2060]), (4, [2060, 2110]),
     (5, [2110, 2160]), (6, [2160, 2230]), (7, [2600, 2700])],
    complexes=[(3, 4, 5, 6)])


def labels(meta, ref, cmp_):
    results = analyze(aligned(ref, cmp_))
    return [(m.label, m.status) for m in map_comparison_events(meta, results)], results


class DirectMappingTests(unittest.TestCase):
    def test_one_event_maps_to_one_corner(self):
        m = map_event(TEST_CIRCUIT, 500, 640, 600)
        self.assertEqual((m.status, m.label, m.corners), (SINGLE, "T1", (1,)))
        self.assertGreaterEqual(m.confidence, 0.6)

    def test_one_event_maps_to_a_corner_complex(self):
        m = map_event(TEST_CIRCUIT, 1960, 2260, 2120)
        self.assertEqual((m.status, m.label, m.corners), (COMPLEX, "T3-T6", (3, 4, 5, 6)))

    def test_complex_members_are_not_offered_individually(self):
        for minimum in (2030, 2085, 2135, 2190):  # inside T3, T4, T5, T6
            self.assertEqual(map_point(TEST_CIRCUIT, minimum).label, "T3-T6")

    def test_event_in_the_wrong_place_is_unknown_not_forced_onto_a_corner(self):
        m = map_event(TEST_CIRCUIT, 1000, 1100, 1050)  # a straight
        self.assertEqual((m.status, m.label), (UNKNOWN, None))
        self.assertIn("not within any known corner", m.reason)

    def test_event_spanning_several_corners_is_uncertain(self):
        meta = circuit([(10, [600, 700]), (11, [700, 800])])  # two corners, no declared complex
        m = map_event(meta, 610, 790, 650)
        self.assertEqual((m.status, m.label), (UNCERTAIN, None))
        self.assertEqual(m.candidates, ("T10", "T11"))

    def test_weak_overlap_is_uncertain(self):
        # The minimum is just inside T2's range but the event hardly overlaps it.
        m = map_event(TEST_CIRCUIT, 1400, 1565, 1565)
        self.assertEqual((m.status, m.label), (UNCERTAIN, None))

    def test_ambiguous_generic_match_keeps_the_label_with_lower_confidence(self):
        clear = map_event(TEST_CIRCUIT, 500, 640, 600)
        ambiguous = map_event(TEST_CIRCUIT, 500, 640, 600, generic_ambiguous=True)
        self.assertEqual(ambiguous.label, "T1")
        self.assertAlmostEqual(ambiguous.confidence, clear.confidence * 0.5, delta=0.01)

    def test_track_without_metadata_or_distances_is_unknown(self):
        self.assertEqual(map_event(None, 500, 640, 600).status, UNKNOWN)
        no_distances = circuit([(1, None), (2, None)])
        m = map_event(no_distances, 500, 640, 600)
        self.assertEqual((m.status, m.label), (UNKNOWN, None))
        self.assertIn("no corner distances", m.reason)
        self.assertEqual(map_point(None, 600).status, UNKNOWN)

    def test_a_corner_without_a_range_is_skipped_not_guessed(self):
        meta = circuit([(1, None), (2, [1560, 1640])])
        self.assertEqual(map_event(meta, 500, 640, 600).status, UNKNOWN)
        self.assertEqual(map_event(meta, 1500, 1660, 1600).label, "T2")

    def test_a_label_depends_on_distance_never_on_event_order(self):
        # The only event of the lap is at T2's location: it is T2, not "the first corner".
        self.assertEqual(map_event(TEST_CIRCUIT, 1500, 1640, 1600).label, "T2")

    def test_map_point_for_a_single_distance(self):
        self.assertEqual(map_point(TEST_CIRCUIT, 600).label, "T1")
        self.assertEqual(map_point(TEST_CIRCUIT, 1100).status, UNKNOWN)
        self.assertEqual(map_point(circuit([(10, [600, 700]), (11, [695, 800])]), 698).status, UNCERTAIN)


class EndToEndMappingTests(unittest.TestCase):
    """Real detected events from synthetic laps, through analyze() and the mapper."""

    def test_events_get_corner_labels_by_distance(self):
        lap = build_lap([corner(500, 600, 100), corner(1500, 1600, 120)])
        found, _ = labels(TEST_CIRCUIT, lap, build_lap([corner(510, 610, 105), corner(1510, 1610, 125)]))
        self.assertEqual(found, [("T1", SINGLE), ("T2", SINGLE)])

    def test_an_extra_event_does_not_shift_later_corner_labels(self):
        # The comparison lap has an extra braking event on a straight (a lock-up, say) at 1000 m.
        ref = build_lap([corner(500, 600, 100), corner(1500, 1600, 120)])
        cmp_ = build_lap([corner(500, 600, 100), corner(900, 1000, 150), corner(1500, 1600, 120)])
        found, results = labels(TEST_CIRCUIT, ref, cmp_)
        self.assertEqual([r.status for r in results], ["matched", "cmp_only", "matched"])
        self.assertEqual(found, [("T1", SINGLE), (None, UNKNOWN), ("T2", SINGLE)])

    def test_a_lift_only_event_does_not_shift_later_corner_labels(self):
        speed = [(500, 300), (560, 250), (600, 240), (700, 300)]
        lift_only = lap_from(speed, [], [(500, 640, 660)])  # T1 area, lifted but never braked
        ref = build_lap([corner(1500, 1600, 120)])
        cmp_ = lap_from([(500, 300), (560, 250), (600, 240), (700, 300), (1500, 300),
                         (1600, 120), (1700, 300)], [(1500, 1600)], [(495, 640, 660), (1490, 1600, 1640)])
        found, results = labels(TEST_CIRCUIT, ref, cmp_)
        self.assertEqual([r.status for r in results], ["cmp_only", "matched"])
        self.assertEqual(found, [("T1", SINGLE), ("T2", SINGLE)])  # the lift is T1; T2 is still T2
        self.assertIsNone(results[0].cmp.brake_start_m)  # it really is lift-only
        self.assertEqual(lift_only[1], [0.0] * len(lift_only[1]))

    def test_an_unmatched_reference_event_is_labelled_by_its_own_distance(self):
        ref = build_lap([corner(500, 600, 100), corner(1500, 1600, 120)])
        cmp_ = build_lap([corner(1500, 1600, 120)])  # missed T1 entirely
        found, results = labels(TEST_CIRCUIT, ref, cmp_)
        self.assertEqual([r.status for r in results], ["ref_only", "matched"])
        self.assertEqual(found, [("T1", SINGLE), ("T2", SINGLE)])

    def test_a_spin_far_from_any_corner_stays_unknown_and_shifts_nothing(self):
        ref = build_lap([corner(500, 600, 100), corner(2600, 2650, 120)])
        cmp_ = build_lap([corner(500, 600, 100), corner(1100, 1150, 30), corner(2600, 2650, 120)])
        found, _ = labels(TEST_CIRCUIT, ref, cmp_)
        self.assertEqual([f[0] for f in found], ["T1", None, "T7"])

    def test_ambiguous_generic_matching_stays_ambiguous_even_with_a_label(self):
        ref = build_lap([corner(500, 600, 100)])
        cmp_ = build_lap([corner(340, 600, 100)])  # same corner, braking 160 m earlier: ambiguous match
        results = analyze(aligned(ref, cmp_))
        (match,) = map_comparison_events(TEST_CIRCUIT, results)
        self.assertEqual(results[0].status, "ambiguous")  # corner mapping does not touch the generic result
        self.assertEqual((match.status, match.label), (SINGLE, "T1"))  # a label is available...
        self.assertLessEqual(match.confidence, 0.5)  # ...but its confidence reflects the ambiguity

    def test_without_corner_distances_every_event_stays_an_event(self):
        lap = build_lap([corner(500, 600, 100), corner(1500, 1600, 120)])
        found, _ = labels(circuit([(n, None) for n in range(1, 21)]), lap, lap)
        self.assertEqual(found, [(None, UNKNOWN), (None, UNKNOWN)])

    def test_the_event_detector_stays_track_agnostic(self):
        import corner_analysis
        import inspect
        source = inspect.getsource(corner_analysis)
        for word in ("tracks", "metadata", "T1", "COTA", "Texas", "track_id"):
            self.assertNotIn(word, source)


if __name__ == "__main__":
    unittest.main()
