import struct
import unittest

from packet_header import HEADER_SIZE, format_header, parse_header


def make_header(**kw):
    """Build a fake header byte-by-byte per the spec (little endian, packed)."""
    f = dict(
        packet_format=2025, game_year=25, major=1, minor=2, packet_version=1,
        packet_id=6, session_uid=0x1122334455667788, session_time=12.5,
        frame=1000, overall=2000, player=3, secondary=255,
    )
    f.update(kw)
    return (
        struct.pack("<H", f["packet_format"])
        + struct.pack("<BBBBB", f["game_year"], f["major"], f["minor"],
                      f["packet_version"], f["packet_id"])
        + struct.pack("<Q", f["session_uid"])
        + struct.pack("<f", f["session_time"])
        + struct.pack("<II", f["frame"], f["overall"])
        + struct.pack("<BB", f["player"], f["secondary"])
    )


class ParseHeaderTests(unittest.TestCase):
    def test_header_size_is_29(self):
        self.assertEqual(HEADER_SIZE, 29)
        self.assertEqual(len(make_header()), 29)

    def test_parses_all_fields(self):
        h = parse_header(make_header())
        self.assertEqual(h.packet_format, 2025)
        self.assertEqual(h.game_year, 25)
        self.assertEqual(h.game_major_version, 1)
        self.assertEqual(h.game_minor_version, 2)
        self.assertEqual(h.packet_version, 1)
        self.assertEqual(h.packet_id, 6)
        self.assertEqual(h.packet_name, "Car Telemetry")
        self.assertEqual(h.session_uid, 0x1122334455667788)
        self.assertEqual(h.session_time, 12.5)
        self.assertEqual(h.frame_identifier, 1000)
        self.assertEqual(h.overall_frame_identifier, 2000)
        self.assertEqual(h.player_car_index, 3)
        self.assertEqual(h.secondary_player_car_index, 255)

    def test_ignores_trailing_payload(self):
        h = parse_header(make_header() + b"\xff" * 1320)
        self.assertEqual(h.packet_id, 6)

    def test_max_values_not_signed(self):
        h = parse_header(make_header(session_uid=2**64 - 1, frame=2**32 - 1, overall=2**32 - 1))
        self.assertEqual(h.session_uid, 2**64 - 1)
        self.assertEqual(h.frame_identifier, 2**32 - 1)

    def test_too_short_raises(self):
        with self.assertRaises(ValueError):
            parse_header(make_header()[:28])

    def test_format_header_mentions_no_second_player(self):
        text = format_header(parse_header(make_header()))
        self.assertIn("format=2025", text)
        self.assertIn("player2=none", text)


if __name__ == "__main__":
    unittest.main()
