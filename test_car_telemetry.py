import struct
import unittest

from car_telemetry import (
    CAR_SIZE, PACKET_SIZE, format_car_telemetry, parse_car_telemetry,
)
from test_packet_header import make_header


def make_car(speed=0, throttle=0.0, steer=0.0, brake=0.0, clutch=0, gear=0, rpm=0,
             drs=0, rev_pct=0):
    """Build one CarTelemetryData (60 bytes) field by field per the spec."""
    return (
        struct.pack("<H", speed)
        + struct.pack("<fff", throttle, steer, brake)
        + struct.pack("<B", clutch)
        + struct.pack("<b", gear)
        + struct.pack("<H", rpm)
        + struct.pack("<BB", drs, rev_pct)
        + struct.pack("<H", 0x7FFF)  # m_revLightsBitValue
        + struct.pack("<4H", 400, 410, 420, 430)  # brakes temp
        + bytes([90, 91, 92, 93])  # tyre surface temp
        + bytes([95, 96, 97, 98])  # tyre inner temp
        + struct.pack("<H", 105)  # engine temp
        + struct.pack("<4f", 22.5, 22.6, 23.0, 23.1)  # tyre pressure
        + bytes([0, 0, 0, 0])  # surface type
    )


def make_packet(cars, player=0):
    """22 cars (list padded with blank cars) between a header and the 3 trailing bytes."""
    cars = list(cars) + [make_car()] * (22 - len(cars))
    return make_header(packet_id=6, player=player) + b"".join(cars) + bytes([255, 255, 0])


class CarTelemetryTests(unittest.TestCase):
    def test_sizes_match_spec(self):
        self.assertEqual(CAR_SIZE, 60)
        self.assertEqual(PACKET_SIZE, 1352)
        self.assertEqual(len(make_car()), 60)
        self.assertEqual(len(make_packet([])), 1352)

    def test_parses_player_car(self):
        car = make_car(speed=312, throttle=0.75, steer=-0.25, brake=0.5, clutch=10,
                       gear=7, rpm=11500, drs=1, rev_pct=88)
        t = parse_car_telemetry(make_packet([car]), 0)
        self.assertEqual(t.speed_kmh, 312)
        self.assertAlmostEqual(t.throttle, 0.75)
        self.assertAlmostEqual(t.steer, -0.25)
        self.assertAlmostEqual(t.brake, 0.5)
        self.assertEqual(t.clutch, 10)
        self.assertEqual(t.gear, 7)
        self.assertEqual(t.engine_rpm, 11500)
        self.assertEqual(t.drs, 1)
        self.assertEqual(t.rev_lights_percent, 88)

    def test_selects_car_by_index(self):
        cars = [make_car(speed=i * 10) for i in range(22)]
        packet = make_packet(cars, player=5)
        self.assertEqual(parse_car_telemetry(packet, 5).speed_kmh, 50)
        self.assertEqual(parse_car_telemetry(packet, 21).speed_kmh, 210)

    def test_reverse_and_neutral_gear(self):
        packet = make_packet([make_car(gear=-1), make_car(gear=0)])
        self.assertEqual(parse_car_telemetry(packet, 0).gear, -1)
        self.assertIn("gear=R", format_car_telemetry(parse_car_telemetry(packet, 0)))
        self.assertIn("gear=N", format_car_telemetry(parse_car_telemetry(packet, 1)))

    def test_too_short_raises(self):
        with self.assertRaises(ValueError):
            parse_car_telemetry(make_packet([])[:1000], 0)

    def test_bad_car_index_raises(self):
        with self.assertRaises(ValueError):
            parse_car_telemetry(make_packet([]), 22)

    def test_format_percentages(self):
        t = parse_car_telemetry(make_packet([make_car(throttle=1.0, brake=0.25)]), 0)
        text = format_car_telemetry(t)
        self.assertIn("thr="+"100.0%", text)
        self.assertIn("brk= 25.0%", text)


if __name__ == "__main__":
    unittest.main()
