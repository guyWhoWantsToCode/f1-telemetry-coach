import struct
import unittest

from lap_data import (
    LAP_SIZE, PACKET_SIZE, format_lap_data, format_lap_time, parse_lap_data,
)
from test_packet_header import make_header


def make_lap(last_ms=0, cur_ms=0, s1_ms_part=0, s1_min=0, s2_ms_part=0, s2_min=0,
             lap_dist=0.0, total_dist=0.0, position=1, lap_num=1, pit=0, sector=0,
             invalid=0):
    """Build one LapData (57 bytes) field by field per the spec."""
    return (
        struct.pack("<II", last_ms, cur_ms)
        + struct.pack("<HB", s1_ms_part, s1_min)
        + struct.pack("<HB", s2_ms_part, s2_min)
        + struct.pack("<HB", 111, 1)  # delta to car in front
        + struct.pack("<HB", 222, 2)  # delta to race leader
        + struct.pack("<fff", lap_dist, total_dist, 0.5)  # ..., safetyCarDelta
        + bytes([position, lap_num, pit, 3, sector, invalid])  # ..numPitStops=3
        + bytes([4, 5, 6, 7, 8, 9])  # penalties, warnings, cornerCutting, DT, SG, grid
        + bytes([4, 2, 1])  # driverStatus, resultStatus, pitLaneTimerActive
        + struct.pack("<HH", 1234, 2345)  # pit lane time, pit stop timer
        + struct.pack("<B", 1)  # pitStopShouldServePen
        + struct.pack("<f", 330.5)  # speedTrapFastestSpeed
        + struct.pack("<B", 255)  # speedTrapFastestLap
    )


def make_packet(laps, player=0):
    laps = list(laps) + [make_lap()] * (22 - len(laps))
    return make_header(packet_id=2, player=player) + b"".join(laps) + bytes([255, 255])


class LapDataTests(unittest.TestCase):
    def test_sizes_match_spec(self):
        self.assertEqual(LAP_SIZE, 57)
        self.assertEqual(PACKET_SIZE, 1285)
        self.assertEqual(len(make_lap()), 57)
        self.assertEqual(len(make_packet([])), 1285)

    def test_parses_player_car(self):
        lap = make_lap(last_ms=91234, cur_ms=45678, s1_ms_part=28500, s1_min=0,
                       s2_ms_part=5250, s2_min=1, lap_dist=1234.5, total_dist=9876.25,
                       position=7, lap_num=3, pit=1, sector=1, invalid=1)
        d = parse_lap_data(make_packet([lap]), 0)
        self.assertEqual(d.last_lap_time_ms, 91234)
        self.assertEqual(d.current_lap_time_ms, 45678)
        self.assertEqual(d.sector1_time_ms, 28500)
        self.assertEqual(d.sector2_time_ms, 65250)  # 1 min + 5250 ms
        self.assertAlmostEqual(d.lap_distance, 1234.5)
        self.assertAlmostEqual(d.total_distance, 9876.25)
        self.assertEqual(d.car_position, 7)
        self.assertEqual(d.current_lap_num, 3)
        self.assertEqual(d.pit_status, 1)
        self.assertEqual(d.sector, 1)
        self.assertEqual(d.current_lap_invalid, 1)

    def test_negative_distance(self):
        d = parse_lap_data(make_packet([make_lap(lap_dist=-25.0, total_dist=-25.0)]), 0)
        self.assertAlmostEqual(d.lap_distance, -25.0)

    def test_selects_car_by_index(self):
        laps = [make_lap(lap_num=i + 1, position=i + 1) for i in range(22)]
        packet = make_packet(laps, player=9)
        self.assertEqual(parse_lap_data(packet, 9).current_lap_num, 10)
        self.assertEqual(parse_lap_data(packet, 21).car_position, 22)

    def test_too_short_raises(self):
        with self.assertRaises(ValueError):
            parse_lap_data(make_packet([])[:1000], 0)

    def test_bad_car_index_raises(self):
        with self.assertRaises(ValueError):
            parse_lap_data(make_packet([]), 22)

    def test_format_lap_time(self):
        self.assertEqual(format_lap_time(0), "-")
        self.assertEqual(format_lap_time(91234), "1:31.234")
        self.assertEqual(format_lap_time(65250), "1:05.250")

    def test_format_lap_data(self):
        text = format_lap_data(parse_lap_data(make_packet([make_lap(sector=2, invalid=1)]), 0))
        self.assertIn("sector=S3", text)
        self.assertIn("INVALID", text)


if __name__ == "__main__":
    unittest.main()
