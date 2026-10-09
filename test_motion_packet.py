import struct
import unittest

from motion_packet import CAR_SIZE, MOTION_PACKET_ID, PACKET_SIZE, parse_player_position
from test_packet_header import make_header


def make_car_motion(x=0.0, y=0.0, z=0.0, speed_mps=50.0):
    """One 60-byte CarMotionData field by field per the spec."""
    return (
        struct.pack("<fff", x, y, z)                    # m_worldPosition X, Y, Z
        + struct.pack("<fff", speed_mps, 0.0, 0.0)      # m_worldVelocity X, Y, Z
        + struct.pack("<hhh", 32767, 0, 0)              # m_worldForwardDir X, Y, Z
        + struct.pack("<hhh", 0, 0, 32767)              # m_worldRightDir X, Y, Z
        + struct.pack("<fff", 0.1, 0.2, 1.0)            # m_gForce lateral, longitudinal, vertical
        + struct.pack("<fff", 0.5, 0.01, 0.02)          # m_yaw, m_pitch, m_roll
    )


def make_motion_packet(player_xyz, player=0, frame=1, session_uid=0x1122334455667788, others=None):
    """A full 1349-byte Motion packet: the player's car at `player_xyz`, other cars elsewhere."""
    cars = [make_car_motion(1000.0 + i, 5.0, -1000.0 - i) for i in range(22)]
    for index, xyz in (others or {}).items():
        cars[index] = make_car_motion(*xyz)
    cars[player] = make_car_motion(*player_xyz)
    return (make_header(packet_id=MOTION_PACKET_ID, session_uid=session_uid, frame=frame, overall=frame,
                        player=player) + b"".join(cars))


class MotionPacketTests(unittest.TestCase):
    def test_sizes_match_the_spec(self):
        self.assertEqual((CAR_SIZE, PACKET_SIZE), (60, 1349))
        self.assertEqual(len(make_car_motion()), 60)
        self.assertEqual(len(make_motion_packet((1, 2, 3))), 1349)

    def test_reads_the_players_position(self):
        p = parse_player_position(make_motion_packet((123.5, 12.25, -456.75)), 0)
        self.assertEqual((p.x, p.y, p.z), (123.5, 12.25, -456.75))

    def test_selects_the_car_by_index(self):
        packet = make_motion_packet((10.0, 1.0, 20.0), player=7)
        p = parse_player_position(packet, 7)
        self.assertEqual((p.x, p.y, p.z), (10.0, 1.0, 20.0))
        other = parse_player_position(packet, 8)  # a different car in the same packet
        self.assertEqual((other.x, other.z), (1008.0, -1008.0))

    def test_last_car_in_the_array(self):
        p = parse_player_position(make_motion_packet((5.0, 6.0, 7.0), player=21), 21)
        self.assertEqual((p.x, p.y, p.z), (5.0, 6.0, 7.0))

    def test_negative_and_large_coordinates(self):
        p = parse_player_position(make_motion_packet((-2500.5, -30.0, 1800.25)), 0)
        self.assertEqual((p.x, p.y, p.z), (-2500.5, -30.0, 1800.25))

    def test_short_packet_raises(self):
        with self.assertRaises(ValueError):
            parse_player_position(make_motion_packet((1, 2, 3))[:1348], 0)

    def test_bad_car_index_raises(self):
        for index in (-1, 22):
            with self.assertRaises(ValueError):
                parse_player_position(make_motion_packet((1, 2, 3)), index)

    def test_non_finite_position_is_rejected_not_passed_on(self):
        for bad in (float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                parse_player_position(make_motion_packet((bad, 0.0, 0.0)), 0)


if __name__ == "__main__":
    unittest.main()
