import contextlib
import csv
import io
import tempfile
import unittest
from pathlib import Path

import lap_compare
from lap_compare import CompareError, check_laps, common_grid, compare_laps, load_lap, main, summarize
from lap_recorder import CSV_COLUMNS

SESSION = "1122334455667788"


def write_lap(directory, name, distances, time_fn, speed_fn=lambda d: 200.0, gear_fn=lambda d: 4,
              invalid=0, lap=1):
    path = Path(directory) / name
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(CSV_COLUMNS)
        for d in distances:
            w.writerow([lap, d, time_fn(d), speed_fn(d), 0.5, 0.0, 0.1, gear_fn(d), 9000, 0, invalid])
    return path


def frange(start, stop, step):
    out, d = [], start
    while d <= stop + 1e-9:
        out.append(d)
        d += step
    return out


def run_cli(args):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = main(args)
    return code, buf.getvalue()


class LapCompareTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def lap(self, name, dists, time_fn, **kw):
        return load_lap(write_lap(self.dir, name, dists, time_fn, **kw))

    def test_constant_slower_known_delta_with_different_sampling(self):
        # ref: 50 m/s sampled every 5 m from 0; cmp: 45 m/s sampled every 7 m from 3 m.
        ref = self.lap(f"{SESSION}_lap01_1m00.000s.csv", frange(0, 1000, 5), lambda d: d / 50 * 1000)
        cmp_ = self.lap(f"{SESSION}_lap02_1m01.000s.csv", frange(3, 1000, 7), lambda d: d / 45 * 1000)
        rows = compare_laps(ref, cmp_)
        self.assertEqual(rows[0]["distance_m"], 5.0)  # first grid point inside both laps
        self.assertLessEqual(rows[-1]["distance_m"], 997.0)
        for r in rows:
            expected = r["distance_m"] * (1 / 45 - 1 / 50) * 1000
            self.assertAlmostEqual(r["delta_ms"], expected, places=6)
            self.assertGreater(r["delta_ms"], 0)  # comparison slower => positive

    def test_faster_comparison_is_negative(self):
        ref = self.lap("ref.csv", frange(0, 500, 5), lambda d: d / 40 * 1000)
        cmp_ = self.lap("cmp.csv", frange(0, 500, 5), lambda d: d / 50 * 1000)
        rows = compare_laps(ref, cmp_)
        self.assertTrue(all(r["delta_ms"] <= 0 for r in rows))
        self.assertLess(rows[-1]["delta_ms"], 0)
        self.assertIsNone(summarize(rows)["loss"])

    def test_loss_and_gain_locations(self):
        # cmp gains 0.5 ms/m until 400 m (-200 ms), loses 1 ms/m until 800 m (+200 ms), then level.
        def cmp_time(d):
            base = d / 50 * 1000
            if d <= 400:
                return base - 0.5 * d
            if d <= 800:
                return base - 200 + 1.0 * (d - 400)
            return base + 200
        ref = self.lap("ref.csv", frange(0, 1200, 5), lambda d: d / 50 * 1000)
        cmp_ = self.lap("cmp.csv", frange(0, 1200, 5), cmp_time)
        s = summarize(compare_laps(ref, cmp_))
        self.assertEqual(s["gain"][0], 400.0)
        self.assertAlmostEqual(s["gain"][1], -200.0)
        self.assertEqual(s["loss"][0], 800.0)
        self.assertAlmostEqual(s["loss"][1], 200.0)

    def test_no_extrapolation_when_lengths_differ(self):
        ref = self.lap("ref.csv", frange(0, 1000, 5), lambda d: d * 20)
        cmp_ = self.lap("cmp.csv", frange(0, 980, 5), lambda d: d * 22)
        rows = compare_laps(ref, cmp_)
        self.assertEqual(rows[-1]["distance_m"], 980.0)
        self.assertEqual(common_grid(ref, cmp_)[-1], 980.0)

    def test_grid_starts_at_later_start(self):
        ref = self.lap("ref.csv", frange(12, 1000, 5), lambda d: d * 20)
        cmp_ = self.lap("cmp.csv", frange(0, 1000, 5), lambda d: d * 20)
        self.assertEqual(common_grid(ref, cmp_)[0], 15.0)

    def test_length_mismatch_warns_and_big_mismatch_rejected(self):
        ref = self.lap("ref.csv", frange(0, 1000, 5), lambda d: d * 20)
        slightly = self.lap("a.csv", frange(0, 960, 5), lambda d: d * 20)
        self.assertTrue(any("lengths differ" in w for w in check_laps(ref, slightly)))
        short = self.lap("b.csv", frange(0, 500, 5), lambda d: d * 20)
        with self.assertRaises(CompareError):
            check_laps(ref, short)

    def test_invalid_lap_rejected_unless_allowed(self):
        ref = self.lap("ref.csv", frange(0, 500, 5), lambda d: d * 20)
        bad = self.lap("bad.csv", frange(0, 500, 5), lambda d: d * 20, invalid=1)
        with self.assertRaises(CompareError):
            check_laps(ref, bad)
        self.assertTrue(any("INVALID" in w for w in check_laps(ref, bad, allow_invalid=True)))

    def test_different_sessions_warn(self):
        a = self.lap(f"{SESSION}_lap01_1m00.000s.csv", frange(0, 500, 5), lambda d: d * 20)
        b = self.lap("aaaaaaaaaaaaaaaa_lap01_1m00.000s.csv", frange(0, 500, 5), lambda d: d * 20)
        self.assertTrue(any("different sessions" in w for w in check_laps(a, b)))

    def test_gear_is_held_not_interpolated(self):
        def gear(d):
            return 3 if d < 100 else 4
        ref = self.lap("ref.csv", frange(0, 300, 20), lambda d: d * 20, gear_fn=gear)
        cmp_ = self.lap("cmp.csv", frange(0, 300, 5), lambda d: d * 20, gear_fn=gear)
        by_d = {r["distance_m"]: r for r in compare_laps(ref, cmp_)}
        self.assertEqual(by_d[95.0]["ref_gear"], 3)  # ref samples at 80 (gear 3) and 100 (gear 4)
        self.assertEqual(by_d[100.0]["ref_gear"], 4)
        self.assertIsInstance(by_d[95.0]["ref_gear"], int)

    def test_bad_files_raise(self):
        with self.assertRaises(CompareError):
            load_lap(self.dir / "missing.csv")
        p = self.dir / "short.csv"
        p.write_text(",".join(CSV_COLUMNS) + "\n")
        with self.assertRaises(CompareError):
            load_lap(p)
        p2 = write_lap(self.dir, "backwards.csv", [0, 10, 5], lambda d: d)
        with self.assertRaises(CompareError):
            load_lap(p2)

    def test_cli_prints_summary_and_saves_csv(self):
        ref = write_lap(self.dir, f"{SESSION}_lap01_1m00.000s.csv", frange(0, 1000, 5), lambda d: d / 50 * 1000)
        cmp_ = write_lap(self.dir, f"{SESSION}_lap02_1m01.500s.csv", frange(0, 1000, 5), lambda d: d / 45 * 1000)
        out = self.dir / "out"
        code, text = run_cli([str(ref), str(cmp_), "--out-dir", str(out)])
        self.assertEqual(code, 0)
        self.assertIn("lap time 1:00.000", text)
        self.assertIn("lap time 1:01.500", text)
        self.assertIn("+1.500 s", text)  # official total difference from the filenames
        self.assertIn("Largest accumulated time LOSS", text)
        self.assertIn("Largest accumulated time GAIN: none", text)
        saved = list(out.glob("*.csv"))
        self.assertEqual(len(saved), 1)
        with open(saved[0], newline="") as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(list(rows[0].keys()), lap_compare.OUT_COLUMNS)
        self.assertEqual(float(rows[-1]["distance_m"]), 1000.0)
        self.assertGreater(float(rows[-1]["delta_ms"]), 0)

    def test_cli_rejects_invalid_lap(self):
        ref = write_lap(self.dir, "ref.csv", frange(0, 500, 5), lambda d: d * 20)
        bad = write_lap(self.dir, "bad.csv", frange(0, 500, 5), lambda d: d * 20, invalid=1)
        code, text = run_cli([str(ref), str(bad), "--out-dir", str(self.dir / "o")])
        self.assertEqual(code, 1)
        self.assertIn("INVALID", text)
        self.assertFalse((self.dir / "o").exists())


if __name__ == "__main__":
    unittest.main()
