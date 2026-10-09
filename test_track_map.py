"""Tests for recording world positions and building circuit traces. Scratch directories only."""

import csv
import json
import math
import tempfile
import time
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from api.main import create_app
from api.recording import RecordingService
from lap_data import parse_lap_data
from lap_recorder import CSV_COLUMNS, LapRecorder
from motion_packet import WorldPosition
from car_telemetry import parse_car_telemetry
from session_packet import SessionInfo
from test_car_telemetry import make_car, make_packet as make_telemetry_packet
from test_lap_data import make_lap, make_packet as make_lap_packet
from test_motion_packet import make_motion_packet
from test_recording import UdpSender, wait_for
from test_session_packet import make_session_packet
from test_tracks import COTA, MONZA, SESSION_A, SESSION_B, lap_filename, make_metadata_dir
from tracks.geometry import GeometryConfig, LapInput, build_geometry, interpolate, orientation
from tracks.positions import LapPath, PositionStore
from tracks.service import TrackService

LENGTH = 3000.0


def circuit_point(d, mirror=False, offset=0.0, length=LENGTH):
    """A point on a closed synthetic circuit, `d` metres along it (x, y, z), plus its heading.

    The outline r(a) = R * (1 + 0.3 cos 2a + 0.15 sin 3a) is traversed so that corners turn
    clockwise in the X/Z plane (X right, Z down): right turns when seen from above. `offset`
    shifts the racing line sideways by that many metres. `mirror` negates Z, as if the game's
    world were the mirror image of what the X/Z plane suggests.
    """
    radius = length / (2 * math.pi)

    def at(a):
        r = radius * (1 + 0.3 * math.cos(2 * a) + 0.15 * math.sin(3 * a))
        return r * math.cos(a), r * math.sin(a)

    # Arc-length parameterisation by numerical integration (fine step, cached). The outline is
    # scaled so its perimeter is exactly `length`: lap distance then equals metres along the path.
    table = circuit_point.__dict__.setdefault("_table", {})
    if length not in table:
        pts, acc, a = [(0.0, 0.0)], 0.0, 0.0
        n = 20000
        for i in range(1, n + 1):
            a1 = 2 * math.pi * i / n
            acc += math.dist(at(a), at(a1))
            pts.append((acc, a1))
            a = a1
        table[length] = pts
    pts = table[length]
    total = pts[-1][0]
    scale = length / total
    s = (d / length) * total
    lo, hi = 0, len(pts) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        (lo, hi) = (mid, hi) if pts[mid][0] <= s else (lo, mid)
    frac = (s - pts[lo][0]) / max(pts[hi][0] - pts[lo][0], 1e-9)
    a = pts[lo][1] + frac * (pts[hi][1] - pts[lo][1])
    x, z = (v * scale for v in at(a))
    ax, az = (v * scale for v in at(a + 1e-3))
    nx, nz = -(az - z), ax - x  # a normal for the sideways offset
    norm = math.hypot(nx, nz) or 1.0
    x, z = x + offset * nx / norm, z + offset * nz / norm
    y = 20.0 + 15.0 * math.sin(2 * math.pi * d / length)  # gentle elevation: Y is the vertical axis
    return (x, y, -z if mirror else z)


def steering_for(d, mirror=False, step=5.0):
    """Steering (right positive) that matches the heading change of the circuit at distance d."""
    p0, p1, p2 = (circuit_point(d + k * step, mirror) for k in (-1, 0, 1))
    h0 = math.atan2(p1[2] - p0[2], p1[0] - p0[0])
    h1 = math.atan2(p2[2] - p1[2], p2[0] - p1[0])
    turn = (h1 - h0 + math.pi) % (2 * math.pi) - math.pi
    # In the true (unmirrored) world a clockwise X/Z turn is a right turn. For the mirrored world the
    # same physical car steers the same way, so the sign follows the unmirrored geometry.
    t0, t1, t2 = (circuit_point(d + k * step, False) for k in (-1, 0, 1))
    g0 = math.atan2(t1[2] - t0[2], t1[0] - t0[0])
    g1 = math.atan2(t2[2] - t1[2], t2[0] - t1[0])
    true_turn = (g1 - g0 + math.pi) % (2 * math.pi) - math.pi
    return max(-1.0, min(1.0, true_turn * 12)) if turn is not None else 0.0


def lap_input(lap_id, mirror=False, offset=0.0, start=0.0, end=LENGTH - 5, step=5.0, declared=LENGTH, skip=()):
    ds = [start + i * step for i in range(int((end - start) / step) + 1)]
    ds = [d for d in ds if not any(a <= d <= b for a, b in skip)]
    pts = [circuit_point(d, mirror, offset) for d in ds]
    return LapInput(lap_id, LapPath(tuple(ds), *(tuple(p[i] for p in pts) for i in range(3))),
                    tuple(ds), tuple(steering_for(d, mirror) for d in ds), declared)


class GeometryTests(unittest.TestCase):
    def setUp(self):
        self.laps = [lap_input(f"lap{i}", offset=o) for i, o in enumerate((-3.0, 0.0, 2.0, 4.0, -1.0))]

    def test_trace_follows_the_true_circuit_without_scaling_or_skewing(self):
        g = build_geometry(self.laps, LENGTH)
        path = g["driver_path"]
        errors = [math.hypot(x - circuit_point(d)[0], z - circuit_point(d)[2])
                  for d, x, z in zip(path["distance_m"], path["x"], path["z"])]
        self.assertLess(max(errors), 3.0)  # within the sideways offsets of the laps
        # Aspect ratio and size are preserved: the X and Z extents match the circuit's.
        truth = [circuit_point(d) for d in path["distance_m"]]
        for axis, key in ((0, "x"), (2, "z")):
            extent = max(path[key]) - min(path[key])
            true_extent = max(t[axis] for t in truth) - min(t[axis] for t in truth)
            self.assertAlmostEqual(extent, true_extent, delta=6.0)
        # Distances between points are real metres: opposite sides of the circuit.
        i = len(path["x"]) // 2
        trace = math.dist((path["x"][0], path["z"][0]), (path["x"][i], path["z"][i]))
        self.assertAlmostEqual(trace, math.dist(circuit_point(0)[::2], circuit_point(path["distance_m"][i])[::2]), delta=6.0)

    def test_quality_report(self):
        q = build_geometry(self.laps, LENGTH)["quality"]
        self.assertEqual((q["lap_count"], q["cross_checked"], q["closed"]), (5, True, True))
        self.assertLess(q["closure_gap_m"], 15)
        self.assertLess(q["spread_m"], 5)
        self.assertAlmostEqual(q["length_ratio"], 1.0, delta=0.03)

    def test_vertical_axis_is_checked_not_assumed(self):
        axes = build_geometry(self.laps, LENGTH)["axes"]
        self.assertEqual((axes["vertical_axis"], axes["vertical_axis_verified"]), ("y", True))
        self.assertLess(axes["spans_m"]["y"], 0.1 * axes["spans_m"]["x"])
        # If Y were not the smallest extent the map would say so instead of pretending.
        flat_x = [LapInput(l.lap_id, LapPath(l.path.distance, tuple(0.0 for _ in l.path.x), l.path.x, l.path.z),
                           l.steer_distance, l.steer, l.declared_length_m) for l in self.laps]
        self.assertFalse(build_geometry(flat_x, LENGTH)["axes"]["vertical_axis_verified"])

    def test_orientation_follows_the_drivers_steering(self):
        g = build_geometry(self.laps, LENGTH)
        self.assertFalse(g["orientation"]["mirror_z"])
        self.assertTrue(g["orientation"]["verified"])
        self.assertGreater(g["orientation"]["r"], 0.5)

    def test_a_mirrored_world_is_detected_and_flagged_for_flipping(self):
        mirrored = [lap_input(f"m{i}", mirror=True, offset=o) for i, o in enumerate((-2.0, 0.0, 3.0))]
        o = build_geometry(mirrored, LENGTH)["orientation"]
        self.assertTrue(o["mirror_z"])
        self.assertLess(o["r"], -0.5)

    def test_no_steering_means_unverified_orientation(self):
        bare = [LapInput(l.lap_id, l.path, (), (), l.declared_length_m) for l in self.laps]
        o = build_geometry(bare, LENGTH)["orientation"]
        self.assertEqual((o["verified"], o["r"], o["mirror_z"]), (False, None, False))
        self.assertIsNone(orientation([0, 5, 10], [0, 1, 2], [0, 0, 0], (), ()))

    def test_one_lap_is_accepted_but_not_cross_checked(self):
        g = build_geometry([self.laps[0]], LENGTH)
        self.assertEqual((g["quality"]["lap_count"], g["quality"]["cross_checked"]), (1, False))

    def test_incomplete_laps_are_rejected_with_a_reason(self):
        partial = lap_input("short", end=1800)
        late_start = lap_input("late", start=300)
        g = build_geometry(self.laps + [partial, late_start], LENGTH)
        reasons = {r["lap_id"]: r["reason"] for r in g["rejected"]}
        self.assertIn("incomplete", reasons["short"])
        self.assertIn("does not start at the line", reasons["late"])
        self.assertNotIn("short", g["laps"])

    def test_a_lap_with_a_hole_in_the_positions_is_rejected(self):
        holey = lap_input("holey", skip=((1000, 1100),))
        self.assertIn("gaps", {r["lap_id"]: r["reason"] for r in build_geometry(self.laps + [holey], LENGTH)["rejected"]}["holey"])

    def test_a_different_circuit_length_is_rejected(self):
        other = lap_input("other_layout", declared=3600.0)
        g = build_geometry(self.laps + [other], LENGTH)
        self.assertIn("3600", {r["lap_id"]: r["reason"] for r in g["rejected"]}["other_layout"])
        self.assertNotIn("other_layout", g["laps"])

    def test_coordinates_of_an_unrelated_circuit_are_never_merged(self):
        # Same length and lap distances, but an entirely different place in the world.
        elsewhere = LapInput("elsewhere", LapPath(self.laps[0].path.distance,
                                                   tuple(x + 900.0 for x in self.laps[0].path.x), self.laps[0].path.y,
                                                   tuple(z - 700.0 for z in self.laps[0].path.z)),
                             self.laps[0].steer_distance, self.laps[0].steer, LENGTH)
        g = build_geometry(self.laps + [elsewhere], LENGTH)
        self.assertIn("elsewhere", {r["lap_id"] for r in g["rejected"]})
        self.assertNotIn("elsewhere", g["laps"])
        self.assertLess(g["quality"]["spread_m"], 5)  # the trace is untouched by the intruder

    def test_no_usable_lap_gives_no_trace(self):
        g = build_geometry([lap_input("short", end=900)], LENGTH)
        self.assertIsNone(g["driver_path"])
        self.assertEqual(len(g["rejected"]), 1)

    def test_interpolation_never_extrapolates(self):
        self.assertEqual(interpolate([0, 10], [0, 100], 5), 50)
        with self.assertRaises(ValueError):
            interpolate([0, 10], [0, 100], 11)
        with self.assertRaises(ValueError):
            interpolate([0, 10], [0, 100], -1)

    def test_step_is_configurable(self):
        g = build_geometry(self.laps, LENGTH, GeometryConfig(step_m=10.0))
        self.assertEqual(g["driver_path"]["distance_m"][1] - g["driver_path"]["distance_m"][0], 10.0)


# ----------------------------------------------------------------------- recording


def lap_frames(recorder, lap_num, last_ms=0, length=600, step=5, frame0=1, position_for=None, order="lmt",
               session_uid=0x1122334455667788):
    """Feed one lap to a LapRecorder: Lap Data, Telemetry and Motion for each game frame, in the
    given arrival order ('l' lap, 't' telemetry, 'm' motion). Returns the saved paths."""
    saved = []
    for i, d in enumerate(range(0, length, step)):
        frame = frame0 + i
        lap = parse_lap_data(make_lap_packet([make_lap(last_ms=last_ms, cur_ms=d * 400, lap_dist=float(d), lap_num=lap_num)]), 0)
        tele = parse_car_telemetry(make_telemetry_packet([make_car(speed=200, throttle=0.5, gear=4, rpm=9000)]), 0)
        pos = position_for(d) if position_for else None
        for kind in order:
            if kind == "l":
                saved.append(recorder.on_lap_data(session_uid, lap, frame))
            elif kind == "t":
                saved.append(recorder.on_telemetry(tele, frame))
            elif kind == "m" and pos is not None:
                recorder.on_motion(WorldPosition(*pos), frame)
    return [p for p in saved if p]


class RecorderPositionTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def record(self, name, order="lmt", with_positions=True, position_for=None):
        laps, positions = self.root / name / "laps", self.root / name / "positions"
        recorder = LapRecorder(laps, positions if with_positions else None)
        pos = position_for or (lambda d: (1000.0 + d, 5.0, -2000.0 + 2 * d))
        saved = lap_frames(recorder, 1, position_for=pos, order=order)
        saved += lap_frames(recorder, 2, last_ms=91234, position_for=pos, order=order, frame0=1000)
        return laps, positions, saved

    def test_positions_are_written_beside_the_lap_not_inside_it(self):
        laps, positions, saved = self.record("a")
        (lap,) = saved
        sidecar = positions / f"{lap.stem}.csv"
        self.assertTrue(sidecar.is_file())
        with open(sidecar, newline="") as f:
            rows = list(csv.DictReader(f))
        with open(lap, newline="") as f:
            lap_rows = list(csv.DictReader(f))
        self.assertEqual(list(rows[0]), ["lap_distance_m", "pos_x", "pos_y", "pos_z"])
        self.assertEqual(len(rows), len(lap_rows))  # one position per saved sample, same order
        for pos, row in zip(rows, lap_rows):
            self.assertEqual(float(pos["lap_distance_m"]), float(row["lap_distance_m"]))
            d = float(row["lap_distance_m"])
            self.assertEqual((float(pos["pos_x"]), float(pos["pos_y"]), float(pos["pos_z"])),
                             (1000.0 + d, 5.0, -2000.0 + 2 * d))
        self.assertEqual(list(lap_rows[0]), CSV_COLUMNS)  # the lap CSV format is unchanged
        self.assertEqual(list(positions.glob("*.csv")), [sidecar])

    def test_lap_csv_is_identical_with_and_without_positions(self):
        _, _, with_pos = self.record("with")
        _, _, without = self.record("without", with_positions=False)
        self.assertEqual(with_pos[0].name, without[0].name)
        self.assertEqual(with_pos[0].read_bytes(), without[0].read_bytes())

    def test_no_sidecar_when_there_is_no_motion_data(self):
        laps, positions, saved = self.record("none", position_for=lambda d: None)
        self.assertEqual(len(saved), 1)
        self.assertFalse(positions.exists() and any(positions.iterdir()))

    def test_positions_pair_by_frame_whatever_the_arrival_order(self):
        for order in ("lmt", "mlt", "ltm", "tlm", "mtl", "tml"):
            _, positions, saved = self.record(f"order_{order}", order=order)
            with open(positions / f"{saved[0].stem}.csv", newline="") as f:
                rows = list(csv.DictReader(f))
            for row in rows:
                d = float(row["lap_distance_m"])
                self.assertEqual(float(row["pos_x"]), 1000.0 + d, f"order {order} at {d} m")

    def test_motion_for_another_frame_is_never_attached(self):
        recorder = LapRecorder(self.root / "laps", self.root / "positions")
        lap = parse_lap_data(make_lap_packet([make_lap(lap_dist=10.0, lap_num=1)]), 0)
        tele = parse_car_telemetry(make_telemetry_packet([make_car()]), 0)
        recorder.on_motion(WorldPosition(1, 2, 3), 99)  # a different frame
        recorder.on_telemetry(tele, 5)
        recorder.on_lap_data(7, lap, 5)
        self.assertEqual(recorder._positions, [None])

    def test_a_missing_position_stays_blank_instead_of_being_filled_in(self):
        pos = lambda d: None if 100 <= d < 200 else (d, 0.0, d)
        laps, positions, saved = self.record("gaps", position_for=pos)
        with open(positions / f"{saved[0].stem}.csv", newline="") as f:
            rows = list(csv.DictReader(f))
        blank = [float(r["lap_distance_m"]) for r in rows if r["pos_x"] == ""]
        self.assertTrue(blank and all(100 <= d < 200 for d in blank))
        read = PositionStore(positions).read(saved[0].stem)
        self.assertFalse(any(100 <= d < 200 for d in read.distance))  # skipped, not interpolated


# ------------------------------------------------------------------------ service


class MapScratch(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.data = self.root / "data"
        (self.data / "laps").mkdir(parents=True)
        self.metadata_dir = make_metadata_dir(self.root)
        self.service = TrackService(self.data, self.metadata_dir)

    def add_lap(self, session, number, time_ms, track=COTA, offset=0.0, mirror=False, positions=True, invalid=False,
                length=3000, shift=(0.0, 0.0), declared=3000):
        """A recorded lap on the synthetic circuit, with its steering, positions and track tag."""
        name = lap_filename(session, number, time_ms, invalid)
        ds = [float(d) for d in range(0, length, 5)]
        with open(self.data / "laps" / name, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(CSV_COLUMNS)
            for d in ds:
                w.writerow([number, d, round(d * 30, 1), 150.0, 1.0, 0.0, round(steering_for(d, mirror), 4), 4, 9000, 0,
                            1 if invalid else 0])
        lap_id = name[:-4]
        if positions:
            pdir = self.data / "positions"
            pdir.mkdir(exist_ok=True)
            with open(pdir / f"{lap_id}.csv", "w", newline="") as f:
                w = csv.writer(f)
                w.writerow(["lap_distance_m", "pos_x", "pos_y", "pos_z"])
                for d in ds:
                    x, y, z = circuit_point(d, mirror, offset)
                    w.writerow([d, round(x + shift[0], 2), round(y, 2), round(z + shift[1], 2)])
        self.service.register_recorded_lap(lap_id, SessionInfo(track, declared, 18, 0), 2025)
        return lap_id

    def map_file(self, track=COTA):
        return self.data / "track_maps" / f"{track}.json"


class TrackServiceMapTests(MapScratch):
    def test_a_trace_is_built_and_persisted_from_valid_complete_laps(self):
        for n, o in enumerate((-2.0, 0.0, 3.0), 1):
            self.add_lap(SESSION_A, n, 100000 + n, offset=o)
        m = self.service.get_map(COTA)
        self.assertTrue(m["available"])
        self.assertEqual(m["kind"], "driver_path")
        self.assertEqual(m["quality"]["lap_count"], 3)
        self.assertEqual(len(m["driver_path"]["x"]), len(m["driver_path"]["distance_m"]))
        self.assertTrue(self.map_file().is_file())
        again = TrackService(self.data, self.metadata_dir)  # a restart
        self.assertEqual(again.get_map(COTA)["laps"], m["laps"])

    def test_the_driver_path_is_never_called_a_centerline(self):
        self.add_lap(SESSION_A, 1, 100000)
        m = self.service.get_map(COTA)
        self.assertEqual(m["centerline"]["available"], False)
        self.assertIn("driver", m["kind"])
        self.assertIsNotNone(m["driver_path"])

    def test_invalid_laps_never_shape_the_trace(self):
        self.add_lap(SESSION_A, 1, 100000)
        bad = self.add_lap(SESSION_A, 2, 99000, invalid=True, offset=30.0)
        m = self.service.get_map(COTA)
        self.assertNotIn(bad, m["laps"])
        self.assertNotIn(bad, [r["lap_id"] for r in m["rejected"]])  # not even considered

    def test_laps_without_positions_give_no_map_and_no_invented_shape(self):
        self.add_lap(SESSION_A, 1, 100000, positions=False)
        m = self.service.get_map(COTA)
        self.assertEqual((m["available"], m["reason"], m["driver_path"]), (False, "no_positions", None))
        self.assertFalse(self.map_file().exists())

    def test_circuits_never_share_coordinates(self):
        for n in (1, 2):
            self.add_lap(SESSION_A, n, 100000 + n, track=COTA, offset=1.0 * n)
        for n in (1, 2):  # a different circuit whose coordinates are elsewhere
            self.add_lap(SESSION_B, n, 80000 + n, track=MONZA, shift=(5000.0, 5000.0), declared=3000)
        cota, monza = self.service.get_map(COTA), self.service.get_map(MONZA)
        self.assertEqual(set(cota["laps"]) & set(monza["laps"]), set())
        self.assertLess(max(cota["driver_path"]["x"]), 1000)  # no point of the Monza data leaked in
        self.assertGreater(min(monza["driver_path"]["x"]), 3000)

    def test_a_lap_assigned_to_the_wrong_circuit_is_rejected_not_merged(self):
        for n in (1, 2, 3):
            self.add_lap(SESSION_A, n, 100000 + n, offset=n)
        stray = self.add_lap(SESSION_B, 1, 100500, shift=(900.0, -700.0))  # same track ID, other place
        m = self.service.get_map(COTA)
        self.assertIn(stray, [r["lap_id"] for r in m["rejected"]])
        self.assertNotIn(stray, m["laps"])
        self.assertLess(m["quality"]["spread_m"], 6)

    def test_a_different_layout_with_another_length_is_rejected(self):
        for n in (1, 2):
            self.add_lap(SESSION_A, n, 100000 + n)
        other = self.add_lap(SESSION_B, 1, 100500, declared=3600)
        m = self.service.get_map(COTA)
        self.assertIn(other, [r["lap_id"] for r in m["rejected"]])

    def test_the_map_is_not_rewritten_when_nothing_changed(self):
        self.add_lap(SESSION_A, 1, 100000)
        mtime = self.map_file().stat().st_mtime_ns
        for _ in range(3):
            self.service.refresh(COTA)
        self.assertEqual(self.map_file().stat().st_mtime_ns, mtime)
        self.add_lap(SESSION_A, 2, 100500)  # a new lap does rebuild it
        self.assertEqual(self.service.get_map(COTA)["quality"]["lap_count"], 2)

    def test_mirrored_world_orientation_is_stored(self):
        for n in (1, 2):
            self.add_lap(SESSION_A, n, 100000 + n, mirror=True)
        o = self.service.get_map(COTA)["orientation"]
        self.assertEqual((o["mirror_z"], o["verified"]), (True, True))

    def test_a_single_lap_path_has_its_own_orientation_and_points(self):
        lap = self.add_lap(SESSION_A, 1, 100000)
        p = self.service.lap_path(lap)
        self.assertEqual((p["available"], p["track_id"], p["point_count"]), (True, COTA, 600))
        self.assertEqual(len(p["x"]), len(p["distance_m"]))
        self.assertTrue(p["orientation"]["verified"])
        self.assertFalse(p["orientation"]["mirror_z"])
        self.assertEqual(p["axes"]["vertical_axis"], "y")

    def test_a_lap_without_positions_reports_why(self):
        lap = self.add_lap(SESSION_A, 1, 100000, positions=False)
        p = self.service.lap_path(lap)
        self.assertEqual((p["available"], p["reason"]), (False, "no_positions"))
        self.assertNotIn("x", p)

    def test_old_recordings_still_work_everywhere(self):
        old = self.add_lap(SESSION_A, 1, 100000, positions=False)
        self.assertFalse(self.service.has_positions(old))
        self.assertEqual(self.service.track_detail(COTA)["stats"]["valid_laps"], 1)

    def test_tracks_report_whether_they_have_a_map(self):
        self.service.activate(SessionInfo(MONZA, 5793, 18, 0), 2025)
        self.add_lap(SESSION_A, 1, 100000)
        flags = {t["track_id"]: t["has_map"] for t in self.service.list_tracks()["tracks"]}
        self.assertEqual(flags, {COTA: True, MONZA: False})


# --------------------------------------------------------------------------- API


class MapApiTests(MapScratch):
    def setUp(self):
        super().setUp()
        self.app = create_app(self.data, udp_port=0, metadata_dir=self.metadata_dir)
        self.client = TestClient(self.app)
        self.addCleanup(self.app.state.recording.stop)
        self.service = self.app.state.tracks

    def test_map_endpoint_returns_the_trace(self):
        for n in (1, 2):
            self.add_lap(SESSION_A, n, 100000 + n, offset=n)
        body = self.client.get(f"/api/tracks/{COTA}/map").json()
        self.assertTrue(body["available"])
        self.assertEqual(body["centerline"]["available"], False)
        self.assertEqual(len(body["driver_path"]["x"]), len(body["driver_path"]["z"]))
        self.assertIn("mirror_z", body["orientation"])

    def test_map_endpoint_empty_state_is_explained_not_faked(self):
        self.service.activate(SessionInfo(MONZA, 5793, 18, 0), 2025)
        body = self.client.get(f"/api/tracks/{MONZA}/map").json()
        self.assertEqual((body["available"], body["reason"], body["driver_path"]), (False, "no_positions", None))
        self.assertIn("Motion", body["message"])
        self.assertEqual(self.client.get("/api/tracks/13/map").status_code, 404)  # no profile

    def test_lap_path_endpoint(self):
        lap = self.add_lap(SESSION_A, 1, 100000)
        body = self.client.get(f"/api/laps/{lap}/path").json()
        self.assertEqual((body["available"], body["point_count"]), (True, 600))
        self.assertEqual(self.client.get("/api/laps/missing/path").status_code, 404)
        self.assertEqual(self.client.get("/api/laps/bad..id/path").status_code, 400)

    def test_lap_without_positions_gets_an_empty_state(self):
        lap = self.add_lap(SESSION_A, 1, 100000, positions=False)
        body = self.client.get(f"/api/laps/{lap}/path").json()
        self.assertEqual((body["available"], body["reason"]), (False, "no_positions"))

    def test_laps_list_says_which_laps_have_positions(self):
        with_pos = self.add_lap(SESSION_A, 1, 100000)
        without = self.add_lap(SESSION_A, 2, 101000, positions=False)
        laps = {l["id"]: l for l in self.client.get("/api/laps").json()["laps"]}
        self.assertEqual((laps[with_pos]["has_positions"], laps[without]["has_positions"]), (True, False))

    def test_tracks_list_carries_has_map(self):
        self.add_lap(SESSION_A, 1, 100000)
        self.assertTrue(self.client.get("/api/tracks").json()["tracks"][0]["has_map"])


# ------------------------------------------------------------ recording end to end


class MotionSender(UdpSender):
    """A fake game: Session, Motion, Lap Data and Car Telemetry for each frame, over UDP."""

    def send_frame(self, distance, lap_num, last_ms=0, mirror=False):
        self.frame += 1
        x, y, z = circuit_point(float(distance), mirror)
        for packet in (
            make_lap_packet_stamped(self.frame, distance, lap_num, last_ms, self.session),
            make_motion_packet((x, y, z), frame=self.frame, session_uid=self.session),
        ):
            self.sock.sendto(packet, self.addr)
        from test_recording import telemetry_packet
        self.sock.sendto(telemetry_packet(self.frame, session=self.session), self.addr)
        if self.frame % 8 == 0:
            time.sleep(0.01)  # let the receiver keep up with the burst


def make_lap_packet_stamped(frame, distance, lap_num, last_ms, session):
    from test_recording import lap_packet
    return lap_packet(frame, distance, lap_num, last_ms, session)


class RecordingMapTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.data = self.root / "data"
        self.metadata_dir = make_metadata_dir(self.root)
        self.tracks = TrackService(self.data, self.metadata_dir)
        self.service = RecordingService(self.data / "laps", port=0, idle_after_s=0.5, tracks=self.tracks,
                                        positions_dir=self.data / "positions")
        self.addCleanup(self.service.stop)
        self.service.start()
        self.sender = MotionSender(self.service.port)
        self.sender.session = 0x1122334455667788
        self.addCleanup(self.sender.close)

    def test_motion_packets_are_recorded_with_their_laps_and_build_a_map(self):
        self.sender.sock.sendto(make_session_packet(track_id=COTA, track_length=3000, session_uid=self.sender.session),
                                self.sender.addr)
        self.assertTrue(wait_for(lambda: self.service.status()["active_track_id"] == COTA))
        for lap in (1, 2, 3):
            for d in range(0, 3000, 10):
                self.sender.send_frame(d, lap, last_ms=90000 + lap)
        self.assertTrue(wait_for(lambda: self.service.status()["laps_saved"] == 2, timeout=20), self.service.status())
        status = self.service.status()
        self.assertGreaterEqual(status["motion_packets"], 600)  # at least the two saved laps
        saved = status["saved_laps"]
        for lap_id in saved:
            self.assertTrue((self.data / "positions" / f"{lap_id}.csv").is_file())
        # The lap is registered (and the trace rebuilt) just after it is counted as saved.
        self.assertTrue(wait_for(lambda: len(self.tracks.get_map(COTA)["laps"]) == 2))
        m = self.tracks.get_map(COTA)
        self.assertTrue(m["available"], m)
        self.assertEqual(sorted(m["laps"]), sorted(saved))
        # The recorded positions are the car's real coordinates, unscaled.
        read = PositionStore(self.data / "positions").read(saved[0])
        x, y, z = circuit_point(read.distance[40])
        self.assertAlmostEqual(read.x[40], x, places=1)
        self.assertAlmostEqual(read.z[40], z, places=1)

    def test_without_motion_packets_laps_still_record_and_no_map_is_invented(self):
        from test_recording import UdpSender as Plain
        sender = Plain(self.service.port)
        self.addCleanup(sender.close)
        sender.sock.sendto(make_session_packet(track_id=COTA, track_length=3000, session_uid=sender.session), sender.addr)
        self.assertTrue(wait_for(lambda: self.service.status()["active_track_id"] == COTA))
        sender.drive_lap(1)
        sender.drive_lap(2, last_ms=91234)
        self.assertTrue(wait_for(lambda: self.service.status()["laps_saved"] == 1))
        self.assertEqual(self.service.status()["motion_packets"], 0)
        self.assertFalse((self.data / "positions").exists())
        self.assertFalse(self.tracks.get_map(COTA)["available"])
        self.assertFalse(self.data.joinpath("track_maps", f"{COTA}.json").exists())

    def test_a_garbage_motion_packet_is_counted_not_fatal(self):
        bad = bytearray(make_motion_packet((1.0, 2.0, 3.0)))
        bad[29:33] = b"\xff\xff\xff\x7f"  # NaN x position
        self.sender.sock.sendto(bytes(bad), self.sender.addr)
        self.assertTrue(wait_for(lambda: self.service.status()["parse_errors"] == 1))
        self.assertTrue(self.service.status()["running"])
        self.assertEqual(self.service.status()["motion_packets"], 0)


if __name__ == "__main__":
    unittest.main()
