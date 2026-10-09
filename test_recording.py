import csv
import socket
import tempfile
import time
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from api.main import create_app
from api.recording import ERROR, IDLE, RECORDING, WAITING, RecordingBusyError, RecordingService, RecordingStartError
from test_car_telemetry import make_car
from test_lap_data import make_lap
from test_packet_header import make_header

SESSION = 0x1122334455667788


def telemetry_packet(frame, speed=200, session=SESSION):
    cars = [make_car(speed=speed, throttle=0.5, gear=4, rpm=9000)] + [make_car()] * 21
    return (make_header(packet_id=6, session_uid=session, frame=frame, overall=frame, player=0)
            + b"".join(cars) + bytes([255, 255, 0]))


def lap_packet(frame, distance, lap_num, last_ms=0, session=SESSION):
    laps = [make_lap(last_ms=last_ms, cur_ms=int(distance * 400), lap_dist=float(distance), lap_num=lap_num)]
    laps += [make_lap()] * 21
    return (make_header(packet_id=2, session_uid=session, frame=frame, overall=frame, player=0)
            + b"".join(laps) + bytes([255, 255]))


def wait_for(condition, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.02)
    return False


class UdpSender:
    def __init__(self, port):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.addr = ("127.0.0.1", port)
        self.frame = 0
        self.session = SESSION  # the session UID stamped on every packet

    def send_distance(self, distance, lap_num, last_ms=0):
        """One game frame: Lap Data and Car Telemetry for the same frame."""
        self.frame += 1
        self.sock.sendto(lap_packet(self.frame, distance, lap_num, last_ms, self.session), self.addr)
        self.sock.sendto(telemetry_packet(self.frame, session=self.session), self.addr)
        time.sleep(0.001)

    def drive_lap(self, lap_num, last_ms=0, length=300, step=5):
        for d in range(0, length, step):
            self.send_distance(d, lap_num, last_ms)

    def close(self):
        self.sock.close()


def port_is_free(port):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.bind(("0.0.0.0", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


class ServiceTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.laps_dir = Path(self._tmp.name) / "laps"
        self.service = RecordingService(self.laps_dir, port=0, idle_after_s=0.5)
        self.addCleanup(self.service.stop)

    def start(self):
        self.service.start()
        sender = UdpSender(self.service.port)
        self.addCleanup(sender.close)
        return sender


class LifecycleTests(ServiceTestCase):
    def test_initial_status_is_idle(self):
        s = self.service.status()
        self.assertEqual((s["state"], s["running"], s["receiving"]), (IDLE, False, False))
        self.assertEqual((s["laps_saved"], s["current_lap"], s["session_uid"], s["last_error"]), (0, None, None, None))

    def test_start_returns_immediately_and_waits_for_packets(self):
        began = time.monotonic()
        self.start()
        self.assertLess(time.monotonic() - began, 1.0)
        s = self.service.status()
        self.assertEqual((s["state"], s["running"], s["receiving"]), (WAITING, True, False))
        self.assertNotEqual(s["port"], 0)

    def test_second_start_is_rejected_and_first_keeps_running(self):
        self.start()
        with self.assertRaises(RecordingBusyError):
            self.service.start()
        self.assertTrue(self.service.status()["running"])

    def test_stop_while_idle_is_clean(self):
        self.service.stop()
        self.service.stop()
        self.assertEqual(self.service.status()["state"], IDLE)

    def test_stop_releases_the_socket_and_allows_restart_cycles(self):
        for _ in range(3):
            self.service.start()
            port = self.service.port
            self.assertFalse(port_is_free(port))  # bound while recording
            self.service.stop()
            self.assertEqual(self.service.status()["state"], IDLE)
            self.assertTrue(port_is_free(port))  # released after stop

    def test_port_already_in_use_reports_error(self):
        blocker = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.addCleanup(blocker.close)
        blocker.bind(("0.0.0.0", 0))
        busy = RecordingService(self.laps_dir, port=blocker.getsockname()[1])
        with self.assertRaises(RecordingStartError):
            busy.start()
        s = busy.status()
        self.assertEqual((s["state"], s["running"]), (ERROR, False))
        self.assertIn("cannot listen on UDP port", s["last_error"])
        busy.stop()  # acknowledges the error
        self.assertEqual(busy.status()["state"], IDLE)
        blocker.close()
        busy.start()  # works once the port is free again
        self.assertTrue(busy.status()["running"])
        busy.stop()


class RecordingTests(ServiceTestCase):
    def test_status_reflects_incoming_packets(self):
        sender = self.start()
        sender.drive_lap(1, length=100)
        self.assertTrue(wait_for(lambda: self.service.status()["state"] == RECORDING))
        s = self.service.status()
        self.assertTrue(s["receiving"])
        self.assertEqual(s["current_lap"], 1)
        self.assertEqual(s["session_uid"], f"{SESSION:016x}")
        self.assertGreater(s["packets_total"], 0)
        # Packets stop: no longer receiving, so back to waiting.
        self.assertTrue(wait_for(lambda: self.service.status()["state"] == WAITING))
        self.assertFalse(self.service.status()["receiving"])
        self.assertEqual(self.service.status()["packets_per_second"], 0.0)

    def test_completed_laps_are_saved_and_counted(self):
        sender = self.start()
        sender.drive_lap(1)
        sender.drive_lap(2, last_ms=91234)  # crossing into lap 2 completes lap 1
        sender.drive_lap(3, last_ms=90000)  # ... and into lap 3 completes lap 2
        self.assertTrue(wait_for(lambda: self.service.status()["laps_saved"] == 2))
        s = self.service.status()
        self.assertEqual(s["current_lap"], 3)
        self.assertEqual(len(s["saved_laps"]), 2)
        self.assertEqual(s["unmatched_samples"], 0)
        self.service.stop()
        files = sorted(self.laps_dir.glob("*.csv"))
        self.assertEqual([f.stem for f in files], sorted(s["saved_laps"]))
        self.assertTrue(files[0].name.startswith(f"{SESSION:016x}_lap01_1m31.234s"))
        with open(files[0], newline="") as f:
            self.assertGreater(len(list(csv.DictReader(f))), 10)

    def test_incomplete_lap_is_not_saved_on_stop(self):
        sender = self.start()
        sender.drive_lap(1, length=200)  # lap 1 never finishes
        self.assertTrue(wait_for(lambda: self.service.status()["current_lap"] == 1))
        self.service.stop()
        self.assertEqual(self.service.status()["laps_saved"], 0)
        self.assertEqual(list(self.laps_dir.glob("*.csv")) if self.laps_dir.exists() else [], [])

    def test_stats_survive_stop_and_reset_on_next_start(self):
        sender = self.start()
        sender.drive_lap(1)
        sender.drive_lap(2, last_ms=91234)
        self.assertTrue(wait_for(lambda: self.service.status()["laps_saved"] == 1))
        self.service.stop()
        self.assertEqual(self.service.status()["laps_saved"], 1)  # still shown after stopping
        self.service.start()
        s = self.service.status()
        self.assertEqual((s["laps_saved"], s["packets_total"], s["current_lap"]), (0, 0, None))

    def test_garbage_packets_are_counted_not_fatal(self):
        sender = self.start()
        sender.sock.sendto(b"short", sender.addr)
        sender.drive_lap(1, length=50)
        self.assertTrue(wait_for(lambda: self.service.status()["parse_errors"] == 1))
        self.assertTrue(self.service.status()["running"])


class ApiTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.data = Path(self._tmp.name)
        self.app = create_app(self.data, udp_port=0)
        self.client = TestClient(self.app)
        self.addCleanup(self.app.state.recording.stop)

    def test_status_start_stop_roundtrip(self):
        self.assertEqual(self.client.get("/api/recording/status").json()["state"], "idle")
        started = self.client.post("/api/recording/start")
        self.assertEqual(started.status_code, 200)
        self.assertEqual((started.json()["state"], started.json()["running"]), ("waiting", True))
        stopped = self.client.post("/api/recording/stop")
        self.assertEqual(stopped.status_code, 200)
        self.assertEqual((stopped.json()["state"], stopped.json()["running"]), ("idle", False))

    def test_start_while_recording_is_409(self):
        self.client.post("/api/recording/start")
        r = self.client.post("/api/recording/start")
        self.assertEqual(r.status_code, 409)
        self.assertIn("already running", r.json()["detail"])
        self.assertTrue(self.client.get("/api/recording/status").json()["running"])

    def test_stop_while_idle_is_200(self):
        r = self.client.post("/api/recording/stop")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["state"], "idle")

    def test_port_in_use_is_409_with_status_error(self):
        blocker = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.addCleanup(blocker.close)
        blocker.bind(("0.0.0.0", 0))
        client = TestClient(create_app(self.data, udp_port=blocker.getsockname()[1]))
        r = client.post("/api/recording/start")
        self.assertEqual(r.status_code, 409)
        self.assertIn("cannot listen on UDP port", r.json()["detail"])
        status = client.get("/api/recording/status").json()
        self.assertEqual(status["state"], "error")
        self.assertIn("cannot listen", status["last_error"])

    def test_recorded_laps_appear_in_laps_endpoint(self):
        port = self.client.post("/api/recording/start").json()["port"]
        sender = UdpSender(port)
        self.addCleanup(sender.close)
        sender.drive_lap(1)
        sender.drive_lap(2, last_ms=91234)
        self.assertTrue(wait_for(lambda: self.client.get("/api/recording/status").json()["laps_saved"] == 1))
        laps = self.client.get("/api/laps").json()["laps"]
        self.assertEqual([(lap["lap_number"], lap["lap_time"]) for lap in laps], [(1, "1:31.234")])

    def test_start_does_not_block_the_request(self):
        began = time.monotonic()
        self.client.post("/api/recording/start")
        self.assertLess(time.monotonic() - began, 1.0)

    def test_shutdown_stops_recording_and_frees_the_port(self):
        with TestClient(self.app) as client:  # runs the lifespan startup/shutdown
            port = client.post("/api/recording/start").json()["port"]
            self.assertFalse(port_is_free(port))
        self.assertFalse(self.app.state.recording.running)
        self.assertTrue(port_is_free(port))


if __name__ == "__main__":
    unittest.main()
