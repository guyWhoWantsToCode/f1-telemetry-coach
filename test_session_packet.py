import struct
import unittest

from packet_header import HEADER_SIZE
from session_packet import PACKET_SIZE, SESSION_PACKET_ID, UNKNOWN_TRACK_ID, parse_session
from test_packet_header import make_header


def make_session_packet(track_id=15, track_length=5513, session_type=18, formula=0, total_laps=0,
                        session_uid=0x1122334455667788, frame=1):
    """A full 753-byte Session packet built field by field from the F1 25 spec."""
    body = (
        struct.pack("<B", 0)                       # m_weather
        + struct.pack("<bb", 28, 22)               # m_trackTemperature, m_airTemperature
        + struct.pack("<B", total_laps)            # m_totalLaps
        + struct.pack("<H", track_length)          # m_trackLength
        + struct.pack("<B", session_type)          # m_sessionType
        + struct.pack("<b", track_id)              # m_trackId
        + struct.pack("<B", formula)               # m_formula
        + struct.pack("<HH", 3600, 3600)           # m_sessionTimeLeft, m_sessionDuration
        + struct.pack("<BBBBBB", 80, 0, 0, 255, 0, 21)  # pit limit, paused, spectating, spectator idx, SLI, numMarshalZones
        + b"".join(struct.pack("<fb", i / 21, 1) for i in range(21))  # m_marshalZones[21]
        + struct.pack("<BBB", 0, 0, 2)             # safety car status, network game, numWeatherForecastSamples
        + b"".join(struct.pack("<BBBbbbbB", session_type, (i * 5) % 250, 0, 28, 2, 22, 2, 10) for i in range(64))  # forecast[64]
        + struct.pack("<BB", 0, 50)                # m_forecastAccuracy, m_aiDifficulty
        + struct.pack("<III", 1, 2, 3)             # season / weekend / session link identifiers
        + struct.pack("<BBB", 0, 0, 0)             # pit stop window ideal / latest, rejoin position
        + bytes([0, 0, 3, 0, 0, 1, 1, 2, 0])       # nine assist fields (steering .. dynamic racing line type)
        + struct.pack("<BB", 5, 2)                 # m_gameMode (Time Trial), m_ruleSet
        + struct.pack("<I", 720)                   # m_timeOfDay
        + struct.pack("<BBBBBBBB", 4, 1, 0, 1, 0, 0, 0, 0)  # session length, 4 unit fields, SC/VSC/red-flag counts
        + bytes(24)                                # 24 single-byte rule settings (equal car perf .. affects licence MP)
        + struct.pack("<B", 1) + bytes(12)         # m_numSessionsInWeekend, m_weekendStructure[12]
        + struct.pack("<ff", 1800.0, 3600.0)       # m_sector2LapDistanceStart, m_sector3LapDistanceStart
    )
    return make_header(packet_id=SESSION_PACKET_ID, session_uid=session_uid, frame=frame, overall=frame) + body


class SessionPacketTests(unittest.TestCase):
    def test_fixture_matches_the_spec_size(self):
        self.assertEqual(PACKET_SIZE, 753)
        self.assertEqual(len(make_session_packet()), 753)

    def test_parses_track_id_and_length(self):
        info = parse_session(make_session_packet(track_id=15, track_length=5513))
        self.assertEqual((info.track_id, info.track_length_m), (15, 5513))

    def test_parses_session_type_and_formula(self):
        info = parse_session(make_session_packet(session_type=18, formula=3))
        self.assertEqual((info.session_type, info.session_type_name, info.formula), (18, "Time Trial", 3))
        self.assertEqual(parse_session(make_session_packet(session_type=15)).session_type_name, "Race")
        self.assertIn("99", parse_session(make_session_packet(session_type=99)).session_type_name)

    def test_unknown_track_value(self):
        self.assertEqual(parse_session(make_session_packet(track_id=-1)).track_id, UNKNOWN_TRACK_ID)

    def test_track_id_outside_the_published_table_is_kept(self):
        self.assertEqual(parse_session(make_session_packet(track_id=99)).track_id, 99)

    def test_other_track_ids(self):
        for track_id, length in ((11, 5793), (13, 5807), (10, 7004), (41, 4259)):
            info = parse_session(make_session_packet(track_id=track_id, track_length=length))
            self.assertEqual((info.track_id, info.track_length_m), (track_id, length))

    def test_trailing_fields_do_not_move_the_decoded_ones(self):
        # The decoded fields sit at fixed offsets right after the header.
        data = bytearray(make_session_packet(track_id=15, track_length=5513))
        data[HEADER_SIZE + 9:] = bytes(len(data) - HEADER_SIZE - 9)  # wipe everything after m_formula
        self.assertEqual(parse_session(bytes(data)).track_id, 15)

    def test_track_length_is_unsigned_16_bit(self):
        self.assertEqual(parse_session(make_session_packet(track_length=65535)).track_length_m, 65535)

    def test_too_short_raises(self):
        with self.assertRaises(ValueError):
            parse_session(make_session_packet()[:752])


if __name__ == "__main__":
    unittest.main()
