"""API and recording-service tests for track identity. Scratch directories only."""

import json
import tempfile
import time
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from api.main import create_app
from api.recording import RecordingService
from session_packet import SessionInfo
from test_recording import UdpSender, wait_for
from test_session_packet import make_session_packet
from test_corner_analysis import corner
from test_tracks import (COTA, MONZA, SESSION_A, SESSION_B, SUZUKA, UNLISTED, lap_filename, make_metadata_dir, sha,
                         write_lap)
from tracks.service import TrackService

SESSION_UID_A = int(SESSION_A, 16)
SESSION_UID_B = int(SESSION_B, 16)
TEST_CIRCUIT = 9990


class Scratch(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.data = self.root / "data"
        self.laps = self.data / "laps"
        self.laps.mkdir(parents=True)
        self.metadata_dir = make_metadata_dir(self.root)


class RecordingTrackTests(Scratch):
    """The recording service learns the circuit from Session packets."""

    def setUp(self):
        super().setUp()
        self.tracks = TrackService(self.data, self.metadata_dir)
        self.service = RecordingService(self.laps, port=0, idle_after_s=0.5, tracks=self.tracks)
        self.addCleanup(self.service.stop)
        self.service.start()
        self.sender = UdpSender(self.service.port)
        self.addCleanup(self.sender.close)

    def send_session(self, **kw):
        self.sender.sock.sendto(make_session_packet(**kw), self.sender.addr)

    def status(self):
        return self.service.status()

    def active(self):
        s = self.status()
        return (s["active_track_id"], s["active_track_name"])

    def wait_active(self, track_id):
        self.assertTrue(wait_for(lambda: self.status()["active_track_id"] == track_id), self.status())

    def test_no_track_until_the_game_sends_a_session_packet(self):
        s = self.status()
        self.assertEqual((s["active_track_id"], s["active_track_name"], s["track_length_m"]), (None, None, None))

    def test_session_packet_sets_the_active_track(self):
        self.send_session(track_id=COTA, track_length=5513, session_type=18, session_uid=SESSION_UID_A)
        self.wait_active(15)
        s = self.status()
        self.assertEqual((s["active_track_name"], s["active_track_known"], s["track_length_m"]),
                         ("Circuit of the Americas", True, 5513))
        self.assertEqual((s["session_type"], s["session_type_name"]), (18, "Time Trial"))
        self.assertTrue((self.data / "tracks" / "15.json").is_file())

    def test_repeated_session_packets_do_not_recreate_or_rewrite_the_profile(self):
        calls = []
        real = self.tracks.activate
        self.tracks.activate = lambda *a, **k: calls.append(a) or real(*a, **k)
        for _ in range(15):
            self.send_session(track_id=COTA, session_uid=SESSION_UID_A)
        self.wait_active(15)
        self.assertTrue(wait_for(lambda: self.status()["packets_total"] >= 15))
        profile_path = self.data / "tracks" / "15.json"
        mtime = profile_path.stat().st_mtime_ns
        for _ in range(10):
            self.send_session(track_id=COTA, session_uid=SESSION_UID_A)
        self.assertTrue(wait_for(lambda: self.status()["packets_total"] >= 25))
        self.assertEqual(len(calls), 1)  # activated once for the whole run of identical packets
        self.assertEqual(profile_path.stat().st_mtime_ns, mtime)

    def test_switching_circuit_updates_the_active_track_without_a_restart(self):
        self.send_session(track_id=COTA, track_length=5513, session_uid=SESSION_UID_A)
        self.wait_active(15)
        cota_before = (self.data / "tracks" / "15.json").read_text()
        self.send_session(track_id=MONZA, track_length=5793, session_uid=SESSION_UID_B)  # new session, new circuit
        self.wait_active(11)
        self.assertEqual(self.active(), (11, "Monza"))
        self.assertEqual(self.status()["track_length_m"], 5793)
        self.assertEqual(self.status()["state"], "recording")  # still the same recording
        self.assertEqual(self.tracks.profiles.list_ids(), [11, 15])
        self.assertEqual((self.data / "tracks" / "15.json").read_text(), cota_before)  # COTA untouched
        self.send_session(track_id=COTA, track_length=5513, session_uid=SESSION_UID_A)  # and back again
        self.wait_active(15)

    def test_unlisted_track_id_is_an_unknown_track_that_keeps_its_number(self):
        self.send_session(track_id=UNLISTED, track_length=4000, session_uid=SESSION_UID_A)
        self.wait_active(99)
        s = self.status()
        self.assertEqual((s["active_track_name"], s["active_track_known"]), ("Unknown track (99)", False))
        self.assertTrue(s["running"])  # no crash
        self.assertEqual(self.tracks.profiles.get(99)["name"], "Unknown track (99)")

    def test_game_reporting_no_track_clears_the_active_track(self):
        self.send_session(track_id=COTA, session_uid=SESSION_UID_A)
        self.wait_active(15)
        self.send_session(track_id=-1, session_uid=SESSION_UID_B)
        self.wait_active(None)
        self.assertEqual(self.tracks.profiles.list_ids(), [15])  # nothing created for "unknown"

    def drive_two_laps(self, first_lap=1):
        self.sender.session = SESSION_UID_A
        self.sender.drive_lap(first_lap)
        self.sender.drive_lap(first_lap + 1, last_ms=91234)

    def test_saved_laps_are_tagged_with_the_circuit_of_their_session(self):
        self.send_session(track_id=COTA, session_uid=SESSION_UID_A)
        self.wait_active(15)
        self.drive_two_laps()
        self.assertTrue(wait_for(lambda: self.status()["laps_saved"] == 1))
        lap_id = self.status()["saved_laps"][0]
        self.assertEqual(self.tracks.lap_track_info(lap_id)["track_id"], 15)
        self.assertEqual(self.tracks.lap_track_info(lap_id)["track_source"], "telemetry")
        sidecar = json.loads((self.laps / f"{lap_id}.meta.json").read_text())
        self.assertEqual((sidecar["track_length_m"], sidecar["game_year"], sidecar["session_type"]), (5513, 2025, 18))
        self.assertEqual(self.tracks.track_detail(15)["stats"]["valid_laps"], 1)

    def test_laps_after_a_circuit_change_belong_to_the_new_circuit_only(self):
        self.send_session(track_id=COTA, session_uid=SESSION_UID_A)
        self.wait_active(15)
        self.drive_two_laps()
        self.assertTrue(wait_for(lambda: self.status()["laps_saved"] == 1))
        first = self.status()["saved_laps"][0]
        self.send_session(track_id=MONZA, track_length=5793, session_uid=SESSION_UID_B)
        self.wait_active(11)
        self.sender.session = SESSION_UID_B  # the game's new session now stamps its own UID
        self.sender.drive_lap(1)
        self.sender.drive_lap(2, last_ms=80000)
        self.assertTrue(wait_for(lambda: self.status()["laps_saved"] == 2))
        second = self.status()["saved_laps"][1]
        self.assertEqual(self.tracks.lap_track_info(first)["track_id"], 15)
        self.assertEqual(self.tracks.lap_track_info(second)["track_id"], 11)
        self.assertEqual(self.tracks.track_detail(15)["stats"]["valid_laps"], 1)
        self.assertEqual(self.tracks.track_detail(11)["stats"]["valid_laps"], 1)

    def test_a_lap_from_a_session_without_a_session_packet_stays_unknown(self):
        self.drive_two_laps()  # no Session packet was ever sent
        self.assertTrue(wait_for(lambda: self.status()["laps_saved"] == 1))
        lap_id = self.status()["saved_laps"][0]
        self.assertEqual(self.tracks.lap_track_info(lap_id)["track_id"], None)
        self.assertFalse((self.laps / f"{lap_id}.meta.json").exists())

    def test_a_track_memory_failure_does_not_stop_the_recording(self):
        def boom(*a, **k):
            raise RuntimeError("disk full")
        self.tracks.activate = boom
        self.send_session(track_id=COTA, session_uid=SESSION_UID_A)
        self.assertTrue(wait_for(lambda: self.status()["track_error"] is not None))
        self.assertIn("disk full", self.status()["track_error"])
        self.assertTrue(self.status()["running"])
        self.assertEqual(self.status()["active_track_id"], 15)  # the circuit is still known

    def test_session_packets_do_not_break_lap_recording(self):
        for _ in range(3):
            self.send_session(track_id=COTA, session_uid=SESSION_UID_A)
            self.sender.drive_lap(1, length=100)
        self.assertTrue(wait_for(lambda: self.status()["current_lap"] == 1))
        self.assertEqual(self.status()["parse_errors"], 0)


class TrackApiTests(Scratch):
    def setUp(self):
        super().setUp()
        self.app = create_app(self.data, udp_port=0, metadata_dir=self.metadata_dir)
        self.client = TestClient(self.app)
        self.addCleanup(self.app.state.recording.stop)
        self.tracks = self.app.state.tracks

    def record(self, session, number, time_ms, track, invalid=False, corners=None):
        write_lap(self.laps, session, number, time_ms, corners or [corner(500, 600, 100)], invalid)
        lap_id = lap_filename(session, number, time_ms, invalid)[:-4]
        self.tracks.register_recorded_lap(lap_id, SessionInfo(track, 5513, 18, 0), 2025)
        return lap_id

    def legacy(self, session=SESSION_A, number=1, time_ms=100000):
        return write_lap(self.laps, session, number, time_ms, [corner(500, 600, 100)]).stem

    # ----------------------------------------------------------------- listing
    def test_tracks_list_starts_empty(self):
        self.assertEqual(self.client.get("/api/tracks").json(),
                         {"tracks": [], "active_track_id": None, "unassigned_laps": 0})

    def test_track_selector_receives_every_known_circuit(self):
        self.record(SESSION_A, 1, 100000, COTA)
        self.record(SESSION_B, 1, 80000, MONZA)
        self.tracks.activate(SessionInfo(SUZUKA, 5807, 18, 0), 2025)  # visited, no laps yet
        body = self.client.get("/api/tracks").json()
        self.assertEqual([t["name"] for t in body["tracks"]], ["Circuit of the Americas", "Monza", "Suzuka"])
        cota = body["tracks"][0]
        self.assertEqual((cota["track_id"], cota["known"], cota["stats"]["valid_laps"], cota["stats"]["sessions"]),
                         (15, True, 1, 1))
        self.assertEqual(cota["stats"]["pb"]["lap_time"], "1:40.000")
        self.assertEqual(body["tracks"][2]["stats"], {"sessions": 0, "valid_laps": 0, "pb": None})

    def test_catalog_lists_assignable_circuits(self):
        tracks = self.client.get("/api/catalog/tracks").json()["tracks"]
        self.assertEqual([t["track_id"] for t in tracks], [11, 13, 15, 9990])
        cota = next(t for t in tracks if t["track_id"] == 15)
        self.assertEqual((cota["name"], cota["has_corner_metadata"]), ("Circuit of the Americas", True))
        self.assertFalse(next(t for t in tracks if t["track_id"] == 13)["has_corner_metadata"])

    def test_track_detail_and_404(self):
        self.record(SESSION_A, 1, 100000, COTA)
        detail = self.client.get("/api/tracks/15").json()
        self.assertEqual((detail["track_id"], detail["laps_learned"], detail["corner_metadata"]["status"]),
                         (15, 1, "corner_numbers_only"))
        self.assertEqual(len(detail["learned_events"]), 1)
        self.assertEqual(self.client.get("/api/tracks/13").status_code, 404)  # no profile yet

    def test_static_corners_endpoint(self):
        cota = self.client.get("/api/tracks/15/corners").json()
        self.assertEqual((cota["available"], cota["has_corner_distances"], len(cota["corners"])), (True, False, 20))
        self.assertIsNone(cota["corners"][0]["range_m"])  # nothing invented
        self.assertEqual(cota["corners"][2]["label"], "T3")
        test_circuit = self.client.get(f"/api/tracks/{TEST_CIRCUIT}/corners").json()
        self.assertEqual(test_circuit["complexes"][0]["label"], "T3-T6")
        no_file = self.client.get("/api/tracks/13/corners").json()
        self.assertEqual((no_file["available"], no_file["corners"]), (False, []))
        self.assertEqual(self.client.get("/api/tracks/4242/corners").status_code, 404)

    # ------------------------------------------------- active vs selected circuit
    def test_active_track_is_independent_from_the_circuit_being_browsed(self):
        self.record(SESSION_A, 1, 100000, COTA)
        self.record(SESSION_B, 1, 80000, MONZA)
        self.app.state.recording.start()
        sender = UdpSender(self.app.state.recording.port)
        self.addCleanup(sender.close)
        sender.sock.sendto(make_session_packet(track_id=COTA, session_uid=SESSION_UID_A), sender.addr)
        self.assertTrue(wait_for(lambda: self.client.get("/api/recording/status").json()["active_track_id"] == 15))

        # Browsing another circuit never changes the live one.
        monza = self.client.get("/api/tracks/11").json()
        self.assertEqual((monza["track_id"], monza["is_active"]), (11, False))
        status = self.client.get("/api/recording/status").json()
        self.assertEqual((status["active_track_id"], status["active_track_name"]), (15, "Circuit of the Americas"))
        listing = self.client.get("/api/tracks").json()
        self.assertEqual(listing["active_track_id"], 15)
        self.assertEqual({t["track_id"]: t["is_active"] for t in listing["tracks"]}, {15: True, 11: False})

        # The game moving to Monza moves the active track; nothing else is needed.
        sender.sock.sendto(make_session_packet(track_id=MONZA, track_length=5793, session_uid=SESSION_UID_B), sender.addr)
        self.assertTrue(wait_for(lambda: self.client.get("/api/recording/status").json()["active_track_id"] == 11))
        self.assertTrue(self.client.get("/api/tracks/11").json()["is_active"])
        self.assertFalse(self.client.get("/api/tracks/15").json()["is_active"])

    # ------------------------------------------------------------ lap metadata
    def test_laps_expose_their_track_and_legacy_laps_are_unknown(self):
        tagged = self.record(SESSION_A, 1, 100000, COTA)
        legacy = self.legacy(SESSION_B, 1, 99000)
        laps = {l["id"]: l for l in self.client.get("/api/laps").json()["laps"]}
        self.assertEqual((laps[tagged]["track_id"], laps[tagged]["track_name"], laps[tagged]["track_source"]),
                         (15, "Circuit of the Americas", "telemetry"))
        self.assertEqual((laps[legacy]["track_id"], laps[legacy]["track_name"]), (None, None))
        self.assertEqual(self.client.get(f"/api/laps/{legacy}").json()["track_id"], None)

    def test_legacy_laps_load_without_errors(self):
        self.legacy()
        body = self.client.get("/api/laps").json()
        self.assertEqual((len(body["laps"]), body["skipped"]), (1, []))
        self.assertEqual(self.client.get("/api/tracks").json()["unassigned_laps"], 1)

    # ------------------------------------------------------ manual assignment
    def test_assigning_a_legacy_lap_persists_and_does_not_touch_the_csv(self):
        lap_id = self.legacy()
        digest = sha(self.laps / f"{lap_id}.csv")
        r = self.client.post(f"/api/laps/{lap_id}/track", json={"track_id": COTA})
        self.assertEqual(r.status_code, 200)
        self.assertEqual((r.json()["track_id"], r.json()["track_source"]), (15, "manual"))
        self.assertEqual(sha(self.laps / f"{lap_id}.csv"), digest)
        again = TestClient(create_app(self.data, udp_port=0, metadata_dir=self.metadata_dir))  # a restart
        self.assertEqual(again.get(f"/api/laps/{lap_id}").json()["track_id"], 15)
        self.assertEqual(again.get("/api/tracks").json()["tracks"][0]["stats"]["valid_laps"], 1)

    def test_nothing_is_assigned_without_a_request(self):
        lap_id = self.legacy()
        self.client.get("/api/laps")
        self.client.get("/api/tracks")
        self.client.get("/api/tracks/15/corners")
        self.assertFalse((self.laps / f"{lap_id}.meta.json").exists())

    def test_assignment_errors(self):
        lap_id = self.legacy()
        self.assertEqual(self.client.post("/api/laps/missing/track", json={"track_id": COTA}).status_code, 404)
        self.assertEqual(self.client.post("/api/laps/bad..id/track", json={"track_id": COTA}).status_code, 400)
        self.assertEqual(self.client.post(f"/api/laps/{lap_id}/track", json={"track_id": 4242}).status_code, 422)
        self.assertEqual(self.client.post(f"/api/laps/{lap_id}/track", json={}).status_code, 422)
        game = self.record(SESSION_B, 1, 99000, MONZA)
        r = self.client.post(f"/api/laps/{game}/track", json={"track_id": COTA})
        self.assertEqual(r.status_code, 409)  # the game said Monza; that cannot be overridden

    def test_assigning_a_whole_session(self):
        self.legacy(SESSION_A, 1)
        self.legacy(SESSION_A, 2, 101000)
        other = self.legacy(SESSION_B, 1, 99000)
        r = self.client.post(f"/api/sessions/{SESSION_A}/track", json={"track_id": COTA})
        self.assertEqual((r.status_code, len(r.json()["assigned"])), (200, 2))
        self.assertEqual(self.client.get(f"/api/laps/{other}").json()["track_id"], None)
        self.assertEqual(self.client.post("/api/sessions/not-a-session/track", json={"track_id": COTA}).status_code, 400)

    # ----------------------------------------------------------- event labels
    def compare(self, ref, cmp_):
        r = self.client.post("/api/compare", json={"reference_id": ref, "comparison_id": cmp_})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()["id"]

    def test_events_carry_corner_labels_and_keep_their_generic_identity(self):
        a = self.record(SESSION_A, 1, 100000, TEST_CIRCUIT, corners=[corner(500, 600, 100), corner(1500, 1600, 120)])
        b = self.record(SESSION_A, 2, 101000, TEST_CIRCUIT, corners=[corner(510, 610, 105), corner(1510, 1610, 125)])
        body = self.client.get(f"/api/comparisons/{self.compare(a, b)}/events").json()
        self.assertEqual((body["track"]["track_id"], body["track"]["has_corner_distances"]), (TEST_CIRCUIT, True))
        e1, e2 = body["events"]
        self.assertEqual((e1["name"], e1["event_number"], e1["corner_label"], e1["corner_status"]),
                         ("Event 1", 1, "T1", "single"))
        self.assertEqual((e2["name"], e2["event_number"], e2["corner_label"]), ("Event 2", 2, "T2"))
        self.assertGreaterEqual(e1["corner_confidence"], 0.6)
        self.assertEqual(e1["status"], "matched")  # generic fields are still there
        self.assertIn("brake_start_diff_m", e1)

    def test_an_extra_event_does_not_relabel_the_events_after_it(self):
        a = self.record(SESSION_A, 1, 100000, TEST_CIRCUIT, corners=[corner(500, 600, 100), corner(1500, 1600, 120)])
        b = self.record(SESSION_A, 2, 101000, TEST_CIRCUIT,
                        corners=[corner(500, 600, 100), corner(900, 1000, 150), corner(1500, 1600, 120)])
        events = self.client.get(f"/api/comparisons/{self.compare(a, b)}/events").json()["events"]
        self.assertEqual([(e["event_number"], e["corner_label"], e["status"]) for e in events],
                         [(1, "T1", "matched"), (2, None, "cmp_only"), (3, "T2", "matched")])
        self.assertEqual(events[1]["corner_status"], "unknown")

    def test_a_circuit_without_corner_distances_keeps_generic_event_names(self):
        a = self.record(SESSION_A, 1, 100000, COTA)
        b = self.record(SESSION_A, 2, 101000, COTA)
        body = self.client.get(f"/api/comparisons/{self.compare(a, b)}/events").json()
        self.assertEqual(body["track"]["track_id"], 15)
        self.assertFalse(body["track"]["has_corner_distances"])
        self.assertEqual([(e["corner_label"], e["corner_status"]) for e in body["events"]], [(None, "unknown")])

    def test_laps_with_unknown_or_different_circuits_get_no_labels(self):
        legacy_a, legacy_b = self.legacy(SESSION_A, 1), self.legacy(SESSION_A, 2, 101000)
        body = self.client.get(f"/api/comparisons/{self.compare(legacy_a, legacy_b)}/events").json()
        self.assertIsNone(body["track"]["track_id"])
        self.assertIn("unknown", body["track"]["reason"])
        self.assertEqual({e["corner_status"] for e in body["events"]}, {"unavailable"})
        self.assertEqual([e["event_number"] for e in body["events"]], [1])  # generic identity intact

        x = self.record(SESSION_B, 1, 99000, TEST_CIRCUIT)
        y = self.record(SESSION_B, 2, 99500, COTA)
        mixed = self.client.get(f"/api/comparisons/{self.compare(x, y)}/events").json()
        self.assertIn("different circuits", mixed["track"]["reason"])
        self.assertEqual({e["corner_label"] for e in mixed["events"]}, {None})

    def test_old_clients_still_get_every_previous_event_field(self):
        a, b = self.legacy(SESSION_A, 1), self.legacy(SESSION_A, 2, 101000)
        event = self.client.get(f"/api/comparisons/{self.compare(a, b)}/events").json()["events"][0]
        for key in ("name", "position_m", "status", "note", "comparable", "time_delta_ms", "ref", "cmp",
                    "ref_events", "cmp_events", "brake_start_diff_m", "min_speed_diff_kmh", "pickup_diff_m",
                    "full_throttle_diff_m"):
            self.assertIn(key, event)


if __name__ == "__main__":
    unittest.main()
