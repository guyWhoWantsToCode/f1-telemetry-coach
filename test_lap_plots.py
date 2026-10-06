import contextlib
import io
import tempfile
import unittest
from pathlib import Path

import lap_plots
from lap_compare import compare_laps, load_lap, save_comparison
from lap_plots import PlotError, lap_info, load_comparison, main, make_plots, summary_text
from test_lap_compare import frange, write_lap

SESSION = "1122334455667788"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class LapPlotsTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        ref = load_lap(write_lap(self.dir, f"{SESSION}_lap02_1m31.200s.csv", frange(0, 1000, 5),
                                 lambda d: d / 50 * 1000))
        cmp_ = load_lap(write_lap(self.dir, f"{SESSION}_lap03_1m31.900s.csv", frange(0, 1000, 5),
                                  lambda d: d / 45 * 1000))
        self.comparison = save_comparison(compare_laps(ref, cmp_), ref, cmp_, self.dir / "comparisons")

    def test_loads_aligned_csv(self):
        data = load_comparison(self.comparison)
        self.assertEqual(data["distance_m"][0], 0.0)
        self.assertEqual(data["distance_m"][-1], 1000.0)
        self.assertEqual(len(data["delta_ms"]), 201)
        self.assertGreater(data["delta_ms"][-1], 0)

    def test_creates_four_plots_and_dashboard(self):
        out = self.dir / "plots"
        written = make_plots(self.comparison, out)
        self.assertEqual(len(written), 5)
        suffixes = sorted(p.stem.rsplit("_", 1)[1] for p in written)
        self.assertEqual(suffixes, ["brake", "dashboard", "delta", "speed", "throttle"])
        for p in written:
            self.assertEqual(p.parent, out)
            self.assertEqual(p.read_bytes()[:8], PNG_SIGNATURE)
            self.assertGreater(p.stat().st_size, 5000)

    def test_lap_info_and_summary_from_filename(self):
        (ref_label, ref_ms), (cmp_label, cmp_ms) = lap_info(self.comparison)
        self.assertEqual((ref_label, ref_ms), ("lap 2", 91200))
        self.assertEqual((cmp_label, cmp_ms), ("lap 3", 91900))
        text = summary_text(load_comparison(self.comparison), self.comparison)
        self.assertIn("1:31.200", text)
        self.assertIn("1:31.900", text)
        self.assertIn("+0.700 s", text)

    def test_summary_falls_back_without_times_in_name(self):
        path = self.dir / "custom.csv"
        path.write_bytes(self.comparison.read_bytes())
        text = summary_text(load_comparison(path), path)
        self.assertIn("Delta at 1000 m", text)

    def test_cli_success_and_output_listing(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = main([str(self.comparison), "--out-dir", str(self.dir / "p")])
        self.assertEqual(code, 0)
        self.assertIn("_dashboard.png", buf.getvalue())
        self.assertEqual(len(list((self.dir / "p").glob("*.png"))), 5)

    def test_bad_input_raises_and_cli_returns_error(self):
        with self.assertRaises(PlotError):
            load_comparison(self.dir / "missing.csv")
        wrong = self.dir / "wrong.csv"
        wrong.write_text("a,b\n1,2\n")
        with self.assertRaises(PlotError):
            load_comparison(wrong)
        empty = self.dir / "empty.csv"
        empty.write_text(",".join(lap_plots.OUT_COLUMNS) + "\n")
        with self.assertRaises(PlotError):
            load_comparison(empty)
        text = self.comparison.read_text().splitlines()
        text[2] = text[2].replace(text[2].split(",")[0], "abc", 1)
        broken = self.dir / "broken.csv"
        broken.write_text("\n".join(text))
        with self.assertRaises(PlotError):
            load_comparison(broken)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = main([str(wrong), "--out-dir", str(self.dir / "never")])
        self.assertEqual(code, 1)
        self.assertIn("Error", buf.getvalue())
        self.assertFalse((self.dir / "never").exists())


if __name__ == "__main__":
    unittest.main()
