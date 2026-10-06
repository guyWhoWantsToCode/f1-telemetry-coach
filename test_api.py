import csv
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from api.main import create_app
from lap_compare import OUT_COLUMNS
from test_corner_analysis import aligned, build_lap, corner
from test_lap_compare import frange, write_lap

SESSION = "1122334455667788"
REF = f"{SESSION}_lap01_1m00.000s"
SLOWER = f"{SESSION}_lap02_1m01.500s"
BAD = f"{SESSION}_lap03_1m02.000s_invalid"


def write_aligned(path, data):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(OUT_COLUMNS)
        for i in range(len(data["distance_m"])):
            w.writerow([data[c][i] for c in OUT_COLUMNS])


class ApiTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.data = Path(self._tmp.name)
        self.laps_dir = self.data / "laps"
        self.laps_dir.mkdir()
        write_lap(self.laps_dir, f"{REF}.csv", frange(0, 1000, 5), lambda d: d / 50 * 1000, lap=1)
        write_lap(self.laps_dir, f"{SLOWER}.csv", frange(0, 1000, 5), lambda d: d / 45 * 1000, lap=2)
        write_lap(self.laps_dir, f"{BAD}.csv", frange(0, 1000, 5), lambda d: d / 40 * 1000, lap=3, invalid=1)
        self.client = TestClient(create_app(self.data))

    def compare(self, ref=REF, cmp_=SLOWER, **extra):
        return self.client.post("/api/compare", json={"reference_id": ref, "comparison_id": cmp_, **extra})


class HealthTests(ApiTestCase):
    def test_health(self):
        r = self.client.get("/api/health")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "ok")
        self.assertTrue(body["laps_dir_exists"])
        self.assertFalse(body["comparisons_dir_exists"])  # created on the first comparison

    def test_missing_data_dir_is_not_an_error(self):
        client = TestClient(create_app(self.data / "nope"))
        self.assertEqual(client.get("/api/health").json()["laps_dir_exists"], False)
        self.assertEqual(client.get("/api/laps").json(), {"laps": [], "skipped": []})


class LapsTests(ApiTestCase):
    def test_list_laps_metadata(self):
        body = self.client.get("/api/laps").json()
        self.assertEqual(body["skipped"], [])
        self.assertEqual([lap["lap_number"] for lap in body["laps"]], [1, 2, 3])
        first = body["laps"][0]
        self.assertEqual(first, {
            "id": REF, "filename": f"{REF}.csv", "session_uid": SESSION, "lap_number": 1,
            "lap_time_ms": 60000, "lap_time": "1:00.000", "valid": True, "samples": 201,
            "start_distance_m": 0.0, "end_distance_m": 1000.0,
        })
        self.assertEqual([lap["valid"] for lap in body["laps"]], [True, True, False])

    def test_unreadable_lap_is_reported_not_fatal(self):
        (self.laps_dir / "broken.csv").write_text("not,a,lap\n1,2,3\n")
        body = self.client.get("/api/laps").json()
        self.assertEqual(len(body["laps"]), 3)
        self.assertEqual([s["id"] for s in body["skipped"]], ["broken"])

    def test_lap_detail_has_samples(self):
        body = self.client.get(f"/api/laps/{REF}").json()
        self.assertEqual(body["id"], REF)
        samples = body["samples_data"]
        self.assertEqual(samples["lap_distance_m"][:3], [0, 5, 10])
        self.assertEqual(len(samples["speed_kmh"]), 201)
        self.assertEqual(set(samples), {
            "lap", "lap_distance_m", "lap_time_ms", "speed_kmh", "throttle", "brake", "steer",
            "gear", "engine_rpm", "drs", "invalid"})
        self.assertEqual(samples["gear"][0], 4)  # integer columns stay integers
        self.assertIsInstance(samples["gear"][0], int)

    def test_unknown_and_malformed_lap_ids(self):
        self.assertEqual(self.client.get("/api/laps/does_not_exist").status_code, 404)
        self.assertEqual(self.client.get("/api/laps/bad..id").status_code, 400)
        self.assertEqual(self.client.get("/api/laps/.hidden").status_code, 400)


class CompareTests(ApiTestCase):
    def test_compare_returns_id_and_summary_and_saves_file(self):
        r = self.compare()
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["id"], f"{REF}__vs__{SLOWER}")
        self.assertTrue((self.data / "comparisons" / f"{body['id']}.csv").is_file())
        self.assertEqual(body["warnings"], [])
        s = body["summary"]
        self.assertEqual(s["total_difference_ms"], 1500)  # official times from the filenames
        self.assertGreater(s["final_delta_ms"], 0)  # comparison slower => positive
        self.assertEqual(s["largest_loss"]["distance_m"], 1000.0)
        self.assertIsNone(s["largest_gain"])
        self.assertEqual((s["points"], s["start_distance_m"], s["end_distance_m"]), (201, 0.0, 1000.0))
        self.assertEqual(body["reference"]["id"], REF)

    def test_compare_errors(self):
        self.assertEqual(self.compare(REF, REF).status_code, 422)
        self.assertEqual(self.compare(REF, "missing").status_code, 404)
        self.assertEqual(self.compare("bad..id", REF).status_code, 400)
        self.assertEqual(self.client.post("/api/compare", json={"reference_id": REF}).status_code, 422)

    def test_invalid_lap_rejected_unless_allowed(self):
        r = self.compare(REF, BAD)
        self.assertEqual(r.status_code, 422)
        self.assertIn("INVALID", r.json()["detail"])
        ok = self.compare(REF, BAD, allow_invalid=True)
        self.assertEqual(ok.status_code, 200)
        self.assertTrue(any("INVALID" in w for w in ok.json()["warnings"]))

    def test_get_comparison_after_compare(self):
        cid = self.compare().json()["id"]
        r = self.client.get(f"/api/comparisons/{cid}")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["id"], cid)
        self.assertEqual(body["summary"]["total_difference_ms"], 1500)
        self.assertEqual(body["reference"]["id"], REF)
        self.assertEqual(body["comparison"]["id"], SLOWER)
        self.assertEqual(set(body["data"]), set(OUT_COLUMNS))
        self.assertEqual(len(body["data"]["delta_ms"]), 201)

    def test_get_comparison_without_lap_files_still_works(self):
        cid = self.compare().json()["id"]
        for path in self.laps_dir.glob("*.csv"):
            path.unlink()
        body = self.client.get(f"/api/comparisons/{cid}").json()
        self.assertIsNone(body["reference"])
        self.assertEqual(body["summary"]["points"], 201)

    def test_unknown_comparison(self):
        self.assertEqual(self.client.get("/api/comparisons/nope").status_code, 404)
        self.assertEqual(self.client.get("/api/comparisons/nope/events").status_code, 404)
        self.assertEqual(self.client.get("/api/comparisons/bad..id").status_code, 400)


class EventsTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        (self.data / "comparisons").mkdir()
        ref = build_lap([corner(500, 600, 100)])
        cmp_ = build_lap([corner(520, 620, 105)])  # brakes 20 m later, 5 km/h faster minimum
        write_aligned(self.data / "comparisons" / "refx__vs__cmpx.csv", aligned(ref, cmp_))
        small = build_lap([corner(500, 600, 285)])  # a 15 km/h dip: below the default threshold
        write_aligned(self.data / "comparisons" / "small__vs__small.csv", aligned(small, small))

    def test_events_use_existing_corner_analysis(self):
        r = self.client.get("/api/comparisons/refx__vs__cmpx/events")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual((body["comparison_id"], body["count"]), ("refx__vs__cmpx", 1))
        ev = body["events"][0]
        self.assertEqual((ev["name"], ev["status"], ev["comparable"]), ("Event 1", "matched", True))
        self.assertEqual(ev["brake_start_diff_m"], 20.0)
        self.assertAlmostEqual(ev["min_speed_diff_kmh"], 5.0)
        self.assertEqual(len(ev["ref_events"]), 1)
        self.assertEqual(ev["ref"]["min_speed_m"], 600.0)
        self.assertEqual(body["thresholds"]["min_drop_kmh"], 20.0)

    def test_threshold_query_parameters(self):
        base = "/api/comparisons/small__vs__small/events"
        self.assertEqual(self.client.get(base).json()["count"], 0)
        r = self.client.get(base, params={"min_drop": 10})
        self.assertEqual(r.json()["count"], 1)
        self.assertEqual(r.json()["thresholds"]["min_drop_kmh"], 10.0)
        self.assertEqual(self.client.get(base, params={"brake_on": 2}).status_code, 422)
        self.assertEqual(self.client.get(base, params={"min_drop": 0}).status_code, 422)

    def test_events_after_compare_endpoint(self):
        cid = self.compare().json()["id"]  # constant-speed laps: valid comparison, no events
        body = self.client.get(f"/api/comparisons/{cid}/events").json()
        self.assertEqual((body["count"], body["events"]), (0, []))

    def test_malformed_comparison_csv_is_422(self):
        (self.data / "comparisons" / "wrong.csv").write_text("a,b\n1,2\n")
        self.assertEqual(self.client.get("/api/comparisons/wrong/events").status_code, 422)


class CorsTests(ApiTestCase):
    def test_vite_origin_allowed(self):
        r = self.client.options("/api/laps", headers={
            "Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"})
        self.assertEqual(r.headers.get("access-control-allow-origin"), "http://localhost:5173")
        r = self.client.get("/api/health", headers={"Origin": "http://127.0.0.1:5173"})
        self.assertEqual(r.headers.get("access-control-allow-origin"), "http://127.0.0.1:5173")

    def test_other_origin_not_allowed(self):
        r = self.client.get("/api/health", headers={"Origin": "http://evil.example"})
        self.assertNotIn("access-control-allow-origin", r.headers)


if __name__ == "__main__":
    unittest.main()
