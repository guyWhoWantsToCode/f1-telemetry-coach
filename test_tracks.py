"""Tests for static circuit metadata, track profiles, lap association, statistics and learning.

Every test works in temporary directories; nothing here touches the real data/ folder.
"""

import csv
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from lap_recorder import CSV_COLUMNS
from session_packet import SessionInfo
from test_corner_analysis import build_lap, corner, times_ms, X
from tracks.lap_tracks import SOURCE_MANUAL, SOURCE_TELEMETRY, LapTrack
from tracks.learning import LearningConfig, ObservedEvent, robust_stats, update_learned_events
from tracks.metadata import MetadataError, MetadataRepository, parse_track_metadata
from tracks.service import TrackConflictError, TrackService, UnknownTrackError

COTA, SUZUKA, MONZA, UNLISTED = 15, 13, 11, 99
SESSION_A = "1122334455667788"
SESSION_B = "aabbccddeeff0011"


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def make_metadata_dir(root):
    """A scratch metadata folder: a small catalog, a corner-less COTA and a calibrated test circuit."""
    meta = Path(root) / "track_metadata"
    write_json(meta / "catalog.json", {"schema_version": 1, "tracks": [
        {"track_id": 15, "name": "Texas", "circuit_name": "Circuit of the Americas"},
        {"track_id": 13, "name": "Suzuka"},
        {"track_id": 11, "name": "Monza"},
        {"track_id": 9990, "name": "Test Circuit"},
    ]})
    write_json(meta / "tracks" / "15.json", {
        "track_id": 15, "name": "Circuit of the Americas", "expected_length_m": 5513,
        "corners": [{"number": n, "range_m": None} for n in range(1, 21)],
        "calibration": {"status": "corner_numbers_only"}})
    write_json(meta / "tracks" / "9990.json", {
        "track_id": 9990, "name": "Test Circuit", "expected_length_m": 3000,
        "corners": [
            {"number": 1, "range_m": [560, 680], "representative_m": 600},
            {"number": 2, "range_m": [1560, 1640]},
            {"number": 3, "range_m": [2000, 2060]}, {"number": 4, "range_m": [2060, 2110]},
            {"number": 5, "range_m": [2110, 2160]}, {"number": 6, "range_m": [2160, 2230]},
            {"number": 7, "range_m": [2600, 2700]},
        ],
        "complexes": [{"corners": [3, 4, 5, 6], "name": "Test Esses"}],
        "calibration": {"status": "complete"}})
    return meta


def lap_filename(session, lap_number, lap_time_ms, invalid=False):
    minutes, rest = divmod(lap_time_ms, 60000)
    return f"{session}_lap{lap_number:02d}_{minutes}m{rest / 1000:06.3f}s{'_invalid' if invalid else ''}.csv"


def write_lap(laps_dir, session, lap_number, lap_time_ms, corners, invalid=False):
    """A recorded-lap CSV with real braking events, named like the recorder names it."""
    speed, brake, throttle = build_lap(corners)
    times = times_ms(speed)
    path = Path(laps_dir) / lap_filename(session, lap_number, lap_time_ms, invalid)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(CSV_COLUMNS)
        for i, d in enumerate(X):
            w.writerow([lap_number, d, round(times[i], 1), round(speed[i], 2), round(throttle[i], 4),
                        round(brake[i], 4), 0.0, 4, 9000, 0, 1 if invalid else 0])
    return path


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class TrackTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.data = self.root / "data"
        self.laps = self.data / "laps"
        self.laps.mkdir(parents=True)
        self.metadata_dir = make_metadata_dir(self.root)
        self.service = self.new_service()

    def new_service(self, **kw):
        return TrackService(self.data, self.metadata_dir, **kw)

    def info(self, track_id, length=5513, session_type=18):
        return SessionInfo(track_id=track_id, track_length_m=length, session_type=session_type, formula=0)


class MetadataTests(TrackTestCase):
    def test_catalog_and_display_names(self):
        repo = MetadataRepository(self.metadata_dir)
        self.assertEqual(repo.display_name(15), "Circuit of the Americas")  # circuit_name wins
        self.assertEqual(repo.display_name(13), "Suzuka")
        self.assertEqual(sorted(repo.catalog()), [11, 13, 15, 9990])

    def test_unknown_track_keeps_its_number(self):
        repo = MetadataRepository(self.metadata_dir)
        self.assertEqual(repo.display_name(UNLISTED), "Unknown track (99)")
        self.assertFalse(repo.is_known(UNLISTED))
        self.assertTrue(repo.is_known(MONZA))

    def test_cota_metadata_has_numbers_but_no_distances(self):
        meta = MetadataRepository(self.metadata_dir).get_track(15)
        self.assertEqual([c.number for c in meta.corners], list(range(1, 21)))
        self.assertFalse(meta.has_corner_distances)
        self.assertEqual(meta.calibration_status, "corner_numbers_only")

    def test_track_without_a_metadata_file(self):
        self.assertIsNone(MetadataRepository(self.metadata_dir).get_track(13))

    def test_complex_range_derives_from_members(self):
        meta = MetadataRepository(self.metadata_dir).get_track(9990)
        (cx,) = meta.complexes
        self.assertEqual((cx.label, cx.range_m), ("T3-T6", (2000.0, 2230.0)))

    def test_malformed_files_are_rejected_with_a_reason(self):
        for bad in ({"track_id": 1}, {"track_id": 1, "name": "x", "corners": [{"number": 1, "range_m": [5, 1]}]},
                    {"track_id": 1, "name": "x", "corners": [{"number": 1}, {"number": 1}]},
                    {"track_id": 1, "name": "x", "corners": [{"number": 1}], "complexes": [{"corners": [1, 2]}]}):
            with self.assertRaises(MetadataError):
                parse_track_metadata(bad)
        write_json(self.metadata_dir / "tracks" / "7.json", {"track_id": 8, "name": "wrong id"})
        repo = MetadataRepository(self.metadata_dir)
        self.assertIsNone(repo.get_track(7))
        self.assertIn("7.json", repo.errors)

    def test_catalog_of_the_real_project_covers_the_spec_tracks(self):
        repo = MetadataRepository()  # the real static metadata shipped with the project
        self.assertEqual(repo.display_name(15), "Circuit of the Americas")
        self.assertEqual(len(repo.catalog()), 27)
        self.assertEqual(repo.catalog()[41].name, "Zandvoort (Reverse)")
        cota = repo.get_track(15)
        self.assertEqual(len(cota.corners), 20)
        self.assertFalse(cota.has_corner_distances)  # nothing invented


class ProfileTests(TrackTestCase):
    def test_activate_creates_a_persistent_profile(self):
        ident = self.service.activate(self.info(COTA), game_year=2025)
        self.assertEqual((ident["track_id"], ident["name"], ident["known"]), (15, "Circuit of the Americas", True))
        path = self.data / "tracks" / "15.json"
        self.assertTrue(path.is_file())
        profile = json.loads(path.read_text())
        self.assertEqual((profile["track_id"], profile["track_length_m"], profile["game_year"]), (15, 5513, 2025))
        self.assertEqual(profile["corner_metadata"], {"track_id": 15})  # a reference, not a copy

    def test_profile_survives_a_restart(self):
        self.service.activate(self.info(COTA), game_year=2025)
        write_lap(self.laps, SESSION_A, 1, 100000, [corner(500, 600, 100)])
        self.service.register_recorded_lap(lap_filename(SESSION_A, 1, 100000)[:-4], self.info(COTA), 2025)
        reloaded = self.new_service()  # a fresh process reading the same folders
        detail = reloaded.track_detail(15)
        self.assertEqual(detail["stats"]["valid_laps"], 1)
        self.assertEqual(detail["stats"]["pb"]["lap_time"], "1:40.000")
        self.assertEqual(detail["track_length_m"], 5513)

    def test_repeated_session_packets_do_not_rewrite_the_profile(self):
        self.service.activate(self.info(COTA), game_year=2025)
        path = self.data / "tracks" / "15.json"
        first = path.stat().st_mtime_ns
        before = path.read_text()
        for _ in range(20):  # the game sends the Session packet about twice a second
            self.service.activate(self.info(COTA), game_year=2025)
        self.assertEqual(path.stat().st_mtime_ns, first)
        self.assertEqual(path.read_text(), before)

    def test_a_changed_length_is_saved(self):
        self.service.activate(self.info(COTA, length=5513), game_year=2025)
        self.service.activate(self.info(COTA, length=5514), game_year=2025)
        self.assertEqual(json.loads((self.data / "tracks" / "15.json").read_text())["track_length_m"], 5514)

    def test_profiles_for_different_circuits_are_independent(self):
        self.service.activate(self.info(COTA), 2025)
        self.service.activate(self.info(MONZA, length=5793), 2025)
        cota_before = (self.data / "tracks" / "15.json").read_text()
        self.service.activate(self.info(SUZUKA, length=5807), 2025)
        self.assertEqual(self.service.profiles.list_ids(), [11, 13, 15])
        self.assertEqual((self.data / "tracks" / "15.json").read_text(), cota_before)  # untouched
        self.assertEqual(json.loads((self.data / "tracks" / "11.json").read_text())["track_length_m"], 5793)

    def test_unknown_game_value_creates_no_profile(self):
        self.assertIsNone(self.service.activate(self.info(-1), 2025))
        self.assertEqual(self.service.profiles.list_ids(), [])

    def test_unlisted_track_id_gets_a_clean_unknown_profile(self):
        ident = self.service.activate(self.info(UNLISTED, length=4000), 2025)
        self.assertEqual((ident["track_id"], ident["name"], ident["known"]), (99, "Unknown track (99)", False))
        self.assertEqual(self.service.profiles.get(99)["track_length_m"], 4000)

    def test_unreadable_profile_is_treated_as_missing(self):
        (self.data / "tracks").mkdir(parents=True)
        (self.data / "tracks" / "15.json").write_text("{not json")
        self.assertIsNone(self.service.profiles.get(15))
        self.service.activate(self.info(COTA), 2025)  # replaces it
        self.assertEqual(self.service.profiles.get(15)["track_id"], 15)


class LapAssociationTests(TrackTestCase):
    def record(self, session, number, time_ms, track=COTA, invalid=False, corners=None):
        write_lap(self.laps, session, number, time_ms, corners or [corner(500, 600, 100)], invalid)
        lap_id = lap_filename(session, number, time_ms, invalid)[:-4]
        self.service.register_recorded_lap(lap_id, self.info(track), 2025)
        return lap_id

    def test_recorded_lap_gets_a_sidecar_and_its_track(self):
        lap_id = self.record(SESSION_A, 1, 100000)
        sidecar = json.loads((self.laps / f"{lap_id}.meta.json").read_text())
        self.assertEqual((sidecar["track_id"], sidecar["source"], sidecar["track_length_m"]), (15, "telemetry", 5513))
        self.assertEqual(self.service.lap_track_info(lap_id),
                         {"track_id": 15, "track_name": "Circuit of the Americas", "track_source": "telemetry"})

    def test_legacy_lap_without_track_info_is_unknown(self):
        path = write_lap(self.laps, SESSION_A, 1, 100000, [corner(500, 600, 100)])
        self.assertEqual(self.service.lap_track_info(path.stem),
                         {"track_id": None, "track_name": None, "track_source": None})
        self.assertEqual(self.service.unassigned_lap_count(), 1)
        self.assertEqual(self.service.profiles.list_ids(), [])  # nothing is inferred or created

    def test_a_lap_length_near_cota_does_not_assign_cota(self):
        path = write_lap(self.laps, SESSION_A, 1, 100000, [corner(500, 600, 100)])
        self.assertIsNone(self.service.lap_tracks.get(path.stem))
        self.service.refresh(COTA)  # even a refresh of COTA does not pull the lap in
        self.assertEqual(self.service.profiles.get(COTA)["stats"]["valid_laps"], 0)

    def test_manual_assignment_persists_and_leaves_telemetry_untouched(self):
        path = write_lap(self.laps, SESSION_A, 1, 100000, [corner(500, 600, 100)])
        digest = sha(path)
        info = self.service.assign_lap(path.stem, COTA)
        self.assertEqual((info["track_id"], info["track_source"]), (15, "manual"))
        self.assertEqual(sha(path), digest)  # the CSV is byte-for-byte unchanged
        again = self.new_service()
        self.assertEqual(again.lap_track_info(path.stem)["track_id"], 15)
        self.assertEqual(again.track_detail(15)["stats"]["valid_laps"], 1)
        self.assertEqual(again.unassigned_lap_count(), 0)

    def test_manual_assignment_validates_lap_and_track(self):
        path = write_lap(self.laps, SESSION_A, 1, 100000, [corner(500, 600, 100)])
        with self.assertRaises(FileNotFoundError):
            self.service.assign_lap("nope", COTA)
        with self.assertRaises(UnknownTrackError):
            self.service.assign_lap(path.stem, 4242)
        self.assertIsNone(self.service.lap_tracks.get(path.stem))

    def test_game_reported_track_cannot_be_overridden(self):
        lap_id = self.record(SESSION_A, 1, 100000, track=COTA)
        with self.assertRaises(TrackConflictError):
            self.service.assign_lap(lap_id, MONZA)
        self.assertEqual(self.service.lap_track_info(lap_id)["track_id"], 15)

    def test_a_manual_assignment_can_be_corrected(self):
        path = write_lap(self.laps, SESSION_A, 1, 100000, [corner(500, 600, 100)])
        self.service.assign_lap(path.stem, COTA)
        self.service.assign_lap(path.stem, MONZA)
        self.assertEqual(self.service.track_detail(COTA)["stats"]["valid_laps"], 0)
        self.assertEqual(self.service.track_detail(MONZA)["stats"]["valid_laps"], 1)

    def test_assigning_a_whole_session(self):
        a = write_lap(self.laps, SESSION_A, 1, 100000, [corner(500, 600, 100)])
        b = write_lap(self.laps, SESSION_A, 2, 101000, [corner(500, 600, 100)])
        other = write_lap(self.laps, SESSION_B, 1, 99000, [corner(500, 600, 100)])
        tagged = self.record("0123456789abcdef", 1, 98000, track=SUZUKA)  # game-reported, same folder
        result = self.service.assign_session(SESSION_A, COTA)
        self.assertEqual(sorted(result["assigned"]), sorted([a.stem, b.stem]))
        self.assertEqual(result["skipped"], [])
        self.assertIsNone(self.service.lap_tracks.get(other.stem))  # other session: not touched
        self.assertEqual(self.service.lap_track_info(tagged)["track_id"], 13)


class StatisticsTests(TrackTestCase):
    def record(self, session, number, time_ms, track, invalid=False):
        write_lap(self.laps, session, number, time_ms, [corner(500, 600, 100)], invalid)
        lap_id = lap_filename(session, number, time_ms, invalid)[:-4]
        self.service.register_recorded_lap(lap_id, self.info(track), 2025)
        return lap_id

    def test_pb_updates_when_a_faster_valid_lap_is_recorded(self):
        self.record(SESSION_A, 1, 101000, COTA)
        self.assertEqual(self.service.track_detail(COTA)["stats"]["pb"]["lap_time_ms"], 101000)
        fast = self.record(SESSION_A, 2, 99500, COTA)
        pb = self.service.track_detail(COTA)["stats"]["pb"]
        self.assertEqual((pb["lap_id"], pb["lap_time_ms"], pb["lap_time"]), (fast, 99500, "1:39.500"))
        self.record(SESSION_A, 3, 100500, COTA)  # slower: PB unchanged
        self.assertEqual(self.service.track_detail(COTA)["stats"]["pb"]["lap_id"], fast)

    def test_invalid_lap_never_becomes_pb_or_counts_as_valid(self):
        valid = self.record(SESSION_A, 1, 101000, COTA)
        self.record(SESSION_A, 2, 95000, COTA, invalid=True)  # much faster, but invalid
        stats = self.service.track_detail(COTA)["stats"]
        self.assertEqual((stats["valid_laps"], stats["pb"]["lap_id"]), (1, valid))

    def test_a_track_with_only_invalid_laps_has_no_pb(self):
        self.record(SESSION_A, 1, 95000, COTA, invalid=True)
        stats = self.service.track_detail(COTA)["stats"]
        self.assertEqual((stats["valid_laps"], stats["pb"]), (0, None))

    def test_circuits_keep_separate_pbs_and_counts(self):
        self.record(SESSION_A, 1, 100000, COTA)
        self.record(SESSION_A, 2, 101000, COTA)
        self.record(SESSION_B, 1, 80000, MONZA)
        cota, monza = self.service.track_detail(COTA)["stats"], self.service.track_detail(MONZA)["stats"]
        self.assertEqual((cota["valid_laps"], cota["sessions"], cota["pb"]["lap_time_ms"]), (2, 1, 100000))
        self.assertEqual((monza["valid_laps"], monza["sessions"], monza["pb"]["lap_time_ms"]), (1, 1, 80000))

    def test_sessions_are_counted_per_circuit(self):
        self.record(SESSION_A, 1, 100000, COTA)
        self.record(SESSION_A, 2, 101000, COTA)
        self.record(SESSION_B, 1, 102000, COTA)
        self.assertEqual(self.service.track_detail(COTA)["stats"]["sessions"], 2)

    def test_reloading_never_double_counts(self):
        self.record(SESSION_A, 1, 100000, COTA)
        self.record(SESSION_A, 2, 101000, COTA)
        for _ in range(5):
            self.service.refresh(COTA)
            self.new_service().list_tracks()
        stats = self.service.track_detail(COTA)["stats"]
        self.assertEqual((stats["valid_laps"], stats["sessions"]), (2, 1))
        self.assertEqual(self.service.profiles.get(COTA)["learning"]["laps_learned"], 2)

    def test_a_deleted_lap_file_leaves_the_statistics(self):
        lap_id = self.record(SESSION_A, 1, 100000, COTA)
        self.record(SESSION_A, 2, 101000, COTA)
        (self.laps / f"{lap_id}.csv").unlink()
        stats = self.service.track_detail(COTA)["stats"]
        self.assertEqual((stats["valid_laps"], stats["pb"]["lap_time_ms"]), (1, 101000))

    def test_track_list_contains_saved_profiles_only(self):
        self.record(SESSION_A, 1, 100000, COTA)
        self.record(SESSION_B, 1, 80000, MONZA)
        self.service.activate(self.info(SUZUKA, length=5807), 2025)
        listing = self.service.list_tracks(active_track_id=SUZUKA)
        self.assertEqual([t["track_id"] for t in listing["tracks"]], [15, 11, 13])  # sorted by name
        self.assertEqual([t["is_active"] for t in listing["tracks"]], [False, False, True])
        self.assertEqual(listing["active_track_id"], 13)
        self.assertEqual(listing["unassigned_laps"], 0)

    def test_an_empty_new_track_profile_has_no_invented_data(self):
        self.service.activate(self.info(MONZA, length=5793), 2025)
        detail = self.service.track_detail(MONZA)
        self.assertEqual(detail["stats"], {"sessions": 0, "valid_laps": 0, "pb": None})
        self.assertEqual((detail["learned_events"], detail["laps_learned"]), ([], 0))

    def test_detail_of_a_circuit_without_a_profile_is_none(self):
        self.assertIsNone(self.service.track_detail(SUZUKA))


class LearningTests(TrackTestCase):
    def test_robust_stats(self):
        median, spread = robust_stats([680, 690, 685, 680])
        self.assertEqual(median, 682.5)
        self.assertLess(spread, 10)

    def learn(self, positions, events=None, laps=0, **cfg):
        events = events or []
        for i, pos in enumerate(positions):
            events, _ = update_learned_events(events, laps + i, [ObservedEvent(pos, pos - 100)], LearningConfig(**cfg))
        return events

    def test_consistent_observations_give_a_stable_location_with_confidence(self):
        (event,) = self.learn([680, 690, 685, 680])
        self.assertAlmostEqual(event["min_speed_m"]["median"], 682.5, delta=1)
        self.assertEqual(event["observations_count"], 4)
        self.assertLess(event["min_speed_m"]["spread"], 8)
        self.assertGreater(event["confidence"], 0.6)
        self.assertAlmostEqual(event["brake_start_m"]["median"], 582.5, delta=1)

    def test_confidence_grows_with_observations(self):
        few = self.learn([680, 685])[0]["confidence"]
        many = self.learn([680, 685, 682, 683, 681, 684])[0]["confidence"]
        self.assertGreater(many, few)

    def test_far_outlier_does_not_move_an_established_event(self):
        events = self.learn([680, 690, 685, 680])
        before = events[0]["min_speed_m"]["median"]
        events, report = update_learned_events(events, 4, [ObservedEvent(800)])  # 115 m away
        established = next(e for e in events if e["min_speed_m"]["median"] < 700)
        self.assertEqual(established["min_speed_m"]["median"], before)
        self.assertEqual(established["observations_count"], 4)
        self.assertEqual(report[0][1], "new")  # a separate, low-confidence candidate
        candidate = next(e for e in events if e["min_speed_m"]["median"] > 700)
        self.assertEqual(candidate["observations_count"], 1)
        self.assertLess(candidate["confidence"], 0.25)

    def test_nearby_outlier_is_rejected_and_counted(self):
        events = self.learn([680, 690, 685, 680])
        events, report = update_learned_events(events, 4, [ObservedEvent(730)])  # 47 m: inside the radius
        (event,) = events
        self.assertEqual(report[0][1], "outlier")
        self.assertEqual((event["outliers_rejected"], event["observations_count"]), (1, 4))
        self.assertAlmostEqual(event["min_speed_m"]["median"], 682.5, delta=1)

    def test_an_early_bad_observation_is_outvoted_by_later_clean_laps(self):
        events = self.learn([900, 684, 686, 682, 685, 683])  # first lap was odd
        best = max(events, key=lambda e: e["confidence"])
        self.assertAlmostEqual(best["min_speed_m"]["median"], 684, delta=3)
        self.assertEqual(best["observations_count"], 5)

    def test_each_lap_teaches_an_event_at_most_once(self):
        events, _ = update_learned_events([], 0, [ObservedEvent(680), ObservedEvent(690)])
        self.assertEqual(len(events), 2)  # two nearby observations in one lap are two events

    def test_rarely_seen_candidates_are_pruned_after_enough_laps(self):
        events = self.learn([680] * 5)
        events, _ = update_learned_events(events, 5, [ObservedEvent(680), ObservedEvent(1500)])
        self.assertEqual(len(events), 2)  # an early one-off becomes a low-confidence candidate...
        for lap in range(6, 14):
            events, _ = update_learned_events(events, lap, [ObservedEvent(680)])
        self.assertEqual([round(e["min_speed_m"]["median"]) for e in events], [680])  # ...then is pruned

    def test_a_one_off_event_late_in_the_history_is_pruned_at_once(self):
        events = self.learn([680] * 12)
        events, _ = update_learned_events(events, 12, [ObservedEvent(680), ObservedEvent(1500)])
        self.assertEqual([round(e["min_speed_m"]["median"]) for e in events], [680])

    def test_input_is_not_modified(self):
        events = self.learn([680, 685])
        snapshot = json.dumps(events, sort_keys=True)
        update_learned_events(events, 2, [ObservedEvent(690), ObservedEvent(1500)])
        self.assertEqual(json.dumps(events, sort_keys=True), snapshot)


class ServiceLearningTests(TrackTestCase):
    def record(self, session, number, time_ms, corners, invalid=False, track=COTA):
        write_lap(self.laps, session, number, time_ms, corners, invalid)
        lap_id = lap_filename(session, number, time_ms, invalid)[:-4]
        self.service.register_recorded_lap(lap_id, self.info(track), 2025)
        return lap_id

    def events(self, track=COTA):
        return self.service.track_detail(track)["learned_events"]

    def test_events_are_learned_from_valid_laps_and_repeat_laps_agree(self):
        for n, min_at in enumerate((600, 605, 595, 600), 1):
            self.record(SESSION_A, n, 100000 + n, [corner(min_at - 100, min_at, 100)])
        (event,) = self.events()
        self.assertAlmostEqual(event["min_speed_m"]["median"], 600, delta=6)
        self.assertEqual(event["observations"], 4)
        self.assertGreater(event["confidence"], 0.6)

    def test_invalid_laps_do_not_update_track_memory(self):
        self.record(SESSION_A, 1, 100000, [corner(500, 600, 100)])
        self.record(SESSION_A, 2, 100500, [corner(1500, 1600, 100)], invalid=True)
        self.assertEqual([round(e["min_speed_m"]["median"]) for e in self.events()], [600])
        self.assertEqual(self.service.profiles.get(COTA)["learning"]["laps_learned"], 1)

    def test_a_far_slower_lap_is_not_learned_from(self):
        self.record(SESSION_A, 1, 100000, [corner(500, 600, 100)])
        self.record(SESSION_A, 2, 140000, [corner(1500, 1600, 100)])  # 40% slower: stopped / crashed
        self.assertEqual(self.service.profiles.get(COTA)["learning"]["laps_learned"], 1)
        self.assertEqual(len(self.events()), 1)

    def test_an_odd_lap_cannot_move_an_established_event(self):
        for n, min_at in enumerate((600, 604, 598, 602), 1):
            self.record(SESSION_A, n, 100000 + n, [corner(min_at - 100, min_at, 100)])
        median = self.events()[0]["min_speed_m"]["median"]
        self.record(SESSION_A, 5, 100100, [corner(630, 730, 100)])  # same corner found 130 m later
        events = self.events()
        established = max(events, key=lambda e: e["observations"])
        self.assertEqual(established["min_speed_m"]["median"], median)
        self.assertEqual(established["observations"], 4)

    def test_learning_is_independent_per_circuit(self):
        self.record(SESSION_A, 1, 100000, [corner(500, 600, 100)], track=COTA)
        self.record(SESSION_B, 1, 80000, [corner(1500, 1600, 100)], track=MONZA)
        self.assertEqual([round(e["min_speed_m"]["median"]) for e in self.events(COTA)], [600])
        self.assertEqual([round(e["min_speed_m"]["median"]) for e in self.events(MONZA)], [1600])

    def test_learned_data_never_changes_static_metadata(self):
        meta_files = {p: p.read_text() for p in (self.metadata_dir / "tracks").glob("*.json")}
        meta_files[self.metadata_dir / "catalog.json"] = (self.metadata_dir / "catalog.json").read_text()
        for n in range(1, 4):
            self.record(SESSION_A, n, 100000 + n, [corner(500, 600, 100)], track=9990)
        self.assertEqual({p: p.read_text() for p in meta_files}, meta_files)
        profile = self.service.profiles.get(9990)
        self.assertNotIn("corners", profile)  # the profile holds a reference, not corner geometry
        self.assertEqual(profile["corner_metadata"], {"track_id": 9990})

    def test_learned_events_are_mapped_to_corners_without_being_stored_as_corners(self):
        for n in range(1, 4):
            self.record(SESSION_A, n, 100000 + n, [corner(500, 600, 100)], track=9990)
        (event,) = self.events(9990)
        self.assertEqual((event["corner"]["status"], event["corner"]["label"]), ("single", "T1"))
        stored = self.service.profiles.get(9990)["learning"]["events"][0]
        self.assertNotIn("corner", stored)  # the label is derived on the fly from static metadata

    def test_a_circuit_without_corner_distances_leaves_learned_events_unlabelled(self):
        self.record(SESSION_A, 1, 100000, [corner(500, 600, 100)], track=COTA)
        self.assertEqual(self.events(COTA)[0]["corner"]["status"], "unknown")


if __name__ == "__main__":
    unittest.main()
