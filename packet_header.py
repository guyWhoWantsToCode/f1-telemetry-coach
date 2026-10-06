"""Parser for the common PacketHeader of the F1 25 UDP format (packet format 2025).

Layout comes from EA's "Data Output from F1 25" specification (docs/f1_25_udp_spec_v3.pdf):
all values are little endian and packed, giving a 29-byte header.
"""

import struct
from dataclasses import dataclass

# uint16 m_packetFormat, uint8 m_gameYear, uint8 m_gameMajorVersion,
# uint8 m_gameMinorVersion, uint8 m_packetVersion, uint8 m_packetId,
# uint64 m_sessionUID, float m_sessionTime, uint32 m_frameIdentifier,
# uint32 m_overallFrameIdentifier, uint8 m_playerCarIndex,
# uint8 m_secondaryPlayerCarIndex
HEADER_STRUCT = struct.Struct("<HBBBBBQfIIBB")
HEADER_SIZE = HEADER_STRUCT.size  # 29

NO_SECOND_PLAYER = 255

# Packet IDs from the spec's "Packet IDs" table (names only, for display).
PACKET_NAMES = {
    0: "Motion",
    1: "Session",
    2: "Lap Data",
    3: "Event",
    4: "Participants",
    5: "Car Setups",
    6: "Car Telemetry",
    7: "Car Status",
    8: "Final Classification",
    9: "Lobby Info",
    10: "Car Damage",
    11: "Session History",
    12: "Tyre Sets",
    13: "Motion Ex",
    14: "Time Trial",
    15: "Lap Positions",
}


@dataclass(frozen=True)
class PacketHeader:
    packet_format: int
    game_year: int
    game_major_version: int
    game_minor_version: int
    packet_version: int
    packet_id: int
    session_uid: int
    session_time: float
    frame_identifier: int
    overall_frame_identifier: int
    player_car_index: int
    secondary_player_car_index: int

    @property
    def packet_name(self):
        return PACKET_NAMES.get(self.packet_id, "Unknown")


def parse_header(data):
    """Parse the PacketHeader at the start of `data`. Raises ValueError if too short."""
    if len(data) < HEADER_SIZE:
        raise ValueError(f"packet too short for header: {len(data)} < {HEADER_SIZE} bytes")
    return PacketHeader(*HEADER_STRUCT.unpack_from(data, 0))


def format_header(h):
    second = "none" if h.secondary_player_car_index == NO_SECOND_PLAYER else h.secondary_player_car_index
    return (
        f"format={h.packet_format} year={h.game_year} "
        f"game={h.game_major_version}.{h.game_minor_version:02d} "
        f"id={h.packet_id}({h.packet_name}) ver={h.packet_version} "
        f"session={h.session_uid:016x} time={h.session_time:.2f}s "
        f"frame={h.frame_identifier} overall={h.overall_frame_identifier} "
        f"player={h.player_car_index} player2={second}"
    )
