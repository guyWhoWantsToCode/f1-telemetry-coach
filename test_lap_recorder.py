import csv
import tempfile
import unittest
from pathlib import Path

from car_telemetry import parse_car_telemetry
from lap_data import parse_lap_data
from lap_recorder import CSV_COLUMNS, LapRecorder
from test_car_telemetry import make_car, make_packet as make_telemetry_packet
from test_lap_data import make_lap, make_packet as make_lap_packet

SESSION = 0x1122334455667788


def feed(recorder, dist, lap_num=1, cur_ms=0, last_ms=0, invalid=0, pit=0, speed=200,
         session=SESSION):
    """Send one telemetry packet and one Lap Data packet through the real parsers."""
    car = make_car(speed=speed, throttle=0.5, brake=0.0, steer=0.1, gear=4, rpm=9000, drs=0)
    recorder.on_telemetry(parse_car_telemetry(make_telemetry_packet([car]), 0))
    lap = make_lap(last_ms=last_ms, cur_ms=cur_ms, lap_dist=dist, lap_num=lap_num,
                   invalid=invalid, pit=pit)
    return recorder.on_lap_data(session, parse_lap_data(make_lap_packet([lap]), 0))


def drive_lap(recorder, lap_num, last_ms, length=200, step=1.0, invalid_from=None):
    """Drive one lap of `length` metres in `step` increments; returns paths saved."""
    saved = []
    d = 0.0
    while d < length:
        invalid = 1 if invalid_from is not None and d >= invalid_from else 0
        path = feed(recorder, d, lap_num=lap_num, cur_ms=int(d * 400), last_ms=last_ms,
                    invalid=invalid)
        saved += [path] if path else []
        d += step
    return saved


def read_rows(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


class LapRecorderTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name) / "laps"
        self.rec = LapRecorder(self.dir)

    def test_records_completed_lap_with_spacing(self):
        drive_lap(self.rec, 1, last_ms=0)
        saved = feed(self.rec, 0.0, lap_num=2, last_ms=80000)  # lap change, time reported
        self.assertIsNotNone(saved)
        rows = read_rows(saved)
        self.assertEqual(list(rows[0].keys()), CSV_COLUMNS)
        dists = [float(r["lap_distance_m"]) for r in rows]
        self.assertEqual(dists, [0.0, 5.0, 10.0] + [float(x) for x in range(15, 200, 5)])
        self.assertTrue(all(r["lap"] == "1" for r in rows))
        self.assertEqual(rows[1]["speed_kmh"], "200")
        self.assertEqual(rows[1]["gear"], "4")
        self.assertEqual(rows[1]["engine_rpm"], "9000")
        self.assertEqual(rows[1]["drs"], "0")
        self.assertEqual(rows[1]["invalid"], "0")

    def test_filename_has_session_lap_and_time(self):
        drive_lap(self.rec, 1, last_ms=0)
        saved = feed(self.rec, 0.0, lap_num=2, last_ms=91234)
        self.assertEqual(saved.name, f"{SESSION:016x}_lap01_1m31.234s.csv")
        self.assertEqual(saved.parent, self.dir)

    def test_lap_time_arrives_a_few_packets_late(self):
        drive_lap(self.rec, 1, last_ms=0)
        self.assertIsNone(feed(self.rec, 0.0, lap_num=2, last_ms=0))  # not updated yet
        saved = feed(self.rec, 1.0, lap_num=2, last_ms=91234)
        self.assertEqual(saved.name, f"{SESSION:016x}_lap01_1m31.234s.csv")

    def test_unknown_time_fallback(self):
        drive_lap(self.rec, 1, last_ms=0)
        saved = None
        for i in range(40):
            saved = feed(self.rec, float(i), lap_num=2, last_ms=0) or saved
        self.assertEqual(saved.name, f"{SESSION:016x}_lap01_unknown.csv")

    def test_invalid_lap_still_saved_and_marked(self):
        drive_lap(self.rec, 1, last_ms=0, invalid_from=100)
        saved = feed(self.rec, 0.0, lap_num=2, last_ms=80000)
        self.assertTrue(saved.name.endswith("_invalid.csv"))
        rows = read_rows(saved)
        self.assertGreater(len(rows), 30)  # recording continued after it went invalid
        self.assertEqual({r["invalid"] for r in rows}, {"1"})  # whole lap flagged

    def test_no_duplicate_samples_when_stationary(self):
        for _ in range(100):  # sitting still at 20 m
            feed(self.rec, 20.0, lap_num=1)
        for d in range(21, 200):
            feed(self.rec, float(d), lap_num=1)
        saved = feed(self.rec, 0.0, lap_num=2, last_ms=80000)
        dists = [float(r["lap_distance_m"]) for r in read_rows(saved)]
        self.assertEqual(dists, [float(x) for x in range(20, 200, 5)])

    def test_mid_lap_join_is_not_recorded(self):
        drive_lap(self.rec, 3, last_ms=0, length=400)  # starts at 0 m: recorded
        # fresh recorder joining at 1500 m of lap 5 -> skipped
        rec2 = LapRecorder(self.dir / "mid")
        for d in range(1500, 1900, 2):
            feed(rec2, float(d), lap_num=5)
        self.assertIsNone(feed(rec2, 0.0, lap_num=6, last_ms=90000))
        self.assertFalse((self.dir / "mid").exists())

    def test_wrap_does_not_leak_into_previous_lap(self):
        for d in range(0, 3000, 5):
            feed(self.rec, float(d), lap_num=1)
        saved = feed(self.rec, 2.0, lap_num=2, last_ms=90000)  # wrapped to ~0 m
        rows = read_rows(saved)
        self.assertEqual(float(rows[-1]["lap_distance_m"]), 2995.0)
        self.assertTrue(all(r["lap"] == "1" for r in rows))
        for d in range(7, 400, 5):
            feed(self.rec, float(d), lap_num=2, last_ms=90000)
        saved2 = feed(self.rec, 0.0, lap_num=3, last_ms=88000)
        self.assertEqual(float(read_rows(saved2)[0]["lap_distance_m"]), 2.0)

    def test_pit_and_negative_distance_samples_skipped(self):
        feed(self.rec, -30.0, lap_num=1)
        feed(self.rec, 10.0, lap_num=1, pit=2)
        for d in range(0, 100, 5):
            feed(self.rec, float(d), lap_num=1)
        saved = feed(self.rec, 0.0, lap_num=2, last_ms=1000)
        self.assertEqual(float(read_rows(saved)[0]["lap_distance_m"]), 0.0)

    def test_new_session_resets(self):
        drive_lap(self.rec, 1, last_ms=0)
        other = 0xAABBCCDDEEFF0011
        saved = feed(self.rec, 0.0, lap_num=1, last_ms=0, session=other)
        # unfinished lap of the old session is not a completed lap, but nothing crashes
        self.assertIsNone(saved)
        self.assertEqual(self.rec._session_uid, other)

    def test_no_telemetry_no_rows(self):
        rec = LapRecorder(self.dir / "none")
        lap = parse_lap_data(make_lap_packet([make_lap(lap_dist=10.0)]), 0)
        self.assertIsNone(rec.on_lap_data(SESSION, lap))
        self.assertEqual(rec._rows, [])


def feed_frame(recorder, frame, dist, lap_num=1, last_ms=0, lap_first=True, with_telemetry=True):
    """One game frame: telemetry speed encodes the frame number so mismatches are visible."""
    car = make_car(speed=frame, throttle=0.5, gear=4, rpm=9000)
    telemetry = parse_car_telemetry(make_telemetry_packet([car]), 0)
    lap = parse_lap_data(make_lap_packet([make_lap(last_ms=last_ms, cur_ms=frame * 10,
                                                   lap_dist=dist, lap_num=lap_num)]), 0)
    saved = []
    steps = [lambda: recorder.on_lap_data(SESSION, lap, frame_id=frame)]
    if with_telemetry:
        steps.insert(0 if not lap_first else 1, lambda: recorder.on_telemetry(telemetry, frame_id=frame))
    for step in steps:
        saved.append(step())
    return next((p for p in saved if p), None)


class FrameMatchingTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.rec = LapRecorder(Path(self._tmp.name))

    def _lap_rows(self, lap_first, skip_frame=None):
        for frame in range(1, 200):  # 1 m per frame, speed == frame number
            feed_frame(self.rec, frame, float(frame), lap_first=lap_first,
                       with_telemetry=frame != skip_frame)
        saved = feed_frame(self.rec, 300, 0.0, lap_num=2, last_ms=80000, lap_first=lap_first)
        return read_rows(saved)

    def test_pairs_same_frame_when_lap_data_arrives_first(self):
        for row in self._lap_rows(lap_first=True):
            self.assertEqual(int(row["speed_kmh"]), round(float(row["lap_distance_m"])))

    def test_pairs_same_frame_when_telemetry_arrives_first(self):
        for row in self._lap_rows(lap_first=False):
            self.assertEqual(int(row["speed_kmh"]), round(float(row["lap_distance_m"])))

    def test_latest_telemetry_fallback_is_one_frame_stale(self):
        # Documents why matching matters: without frame ids, Lap-Data-first gives the old frame.
        for frame in range(1, 200):
            car = make_car(speed=frame)
            self.rec.on_lap_data(SESSION, parse_lap_data(make_lap_packet(
                [make_lap(lap_dist=float(frame))]), 0))
            self.rec.on_telemetry(parse_car_telemetry(make_telemetry_packet([car]), 0))
        saved = self.rec.on_lap_data(SESSION, parse_lap_data(make_lap_packet(
            [make_lap(lap_num=2, last_ms=1)]), 0))
        row = read_rows(saved)[1]
        self.assertEqual(int(row["speed_kmh"]), round(float(row["lap_distance_m"])) - 1)

    def test_missing_telemetry_frame_skips_sample_instead_of_mismatching(self):
        rows = self._lap_rows(lap_first=True, skip_frame=51)
        for row in rows:
            self.assertEqual(int(row["speed_kmh"]), round(float(row["lap_distance_m"])))
        self.assertNotIn(51.0, [float(r["lap_distance_m"]) for r in rows])
        self.assertEqual(self.rec.unmatched_samples, 1)


if __name__ == "__main__":
    unittest.main()
