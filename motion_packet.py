"""Parser for the player's world position in the F1 25 PacketMotionData packet (packet ID 0).

Layout comes from docs/f1_25_udp_spec_v3.pdf ("Motion Packet", 1349 bytes, little endian, packed):

    PacketHeader                      29 bytes
    CarMotionData m_carMotionData[22] 22 x 60 bytes

    struct CarMotionData (60 bytes)
        float m_worldPositionX, m_worldPositionY, m_worldPositionZ    metres      <- decoded
        float m_worldVelocityX, m_worldVelocityY, m_worldVelocityZ    metres/s
        int16 m_worldForwardDirX/Y/Z, m_worldRightDirX/Y/Z            normalised x 32767
        float m_gForceLateral, m_gForceLongitudinal, m_gForceVertical
        float m_yaw, m_pitch, m_roll                                  radians

Only the three position floats are read. The spec does not say which axis is vertical; the map
code verifies that from the data instead of assuming it (see tracks/geometry.py).
"""

import math
import struct
from dataclasses import dataclass

from packet_header import HEADER_SIZE

MOTION_PACKET_ID = 0
NUM_CARS = 22
CAR_SIZE = 60  # sizeof(CarMotionData)
PACKET_SIZE = HEADER_SIZE + NUM_CARS * CAR_SIZE  # 1349, as stated in the spec

_POSITION = struct.Struct("<fff")  # m_worldPositionX, Y, Z at the start of each car


@dataclass(frozen=True)
class WorldPosition:
    x: float
    y: float
    z: float


def parse_player_position(data, car_index):
    """The world position (metres) of one car. Raises ValueError for a short packet, a bad car
    index, or non-finite coordinates (never a made-up position)."""
    if len(data) < PACKET_SIZE:
        raise ValueError(f"motion packet too short: {len(data)} < {PACKET_SIZE} bytes")
    if not 0 <= car_index < NUM_CARS:
        raise ValueError(f"car index {car_index} out of range 0-{NUM_CARS - 1}")
    x, y, z = _POSITION.unpack_from(data, HEADER_SIZE + car_index * CAR_SIZE)
    if not all(math.isfinite(v) for v in (x, y, z)):
        raise ValueError("motion packet has a non-finite position")
    return WorldPosition(x, y, z)
