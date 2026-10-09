"""Parser for the F1 25 PacketSessionData packet (packet ID 1): which circuit is active.

Layout comes from docs/f1_25_udp_spec_v3.pdf ("Session Packet", 753 bytes, little endian,
packed). Only the fields needed to identify the circuit are decoded:

    PacketHeader                    29 bytes   (see packet_header.py)
    uint8  m_weather                 1
    int8   m_trackTemperature        1
    int8   m_airTemperature          1
    uint8  m_totalLaps               1
    uint16 m_trackLength             2   metres
    uint8  m_sessionType             1   see SESSION_TYPE_NAMES
    int8   m_trackId                 1   -1 = unknown, see the "Track IDs" appendix
    uint8  m_formula                 1
    ... (the rest of the 753-byte packet is not needed here)
"""

import struct
from dataclasses import dataclass

from packet_header import HEADER_SIZE

SESSION_PACKET_ID = 1
PACKET_SIZE = 753  # from the spec

# m_weather, m_trackTemperature, m_airTemperature, m_totalLaps, m_trackLength,
# m_sessionType, m_trackId, m_formula
_PREFIX = struct.Struct("<BbbBHBbB")

UNKNOWN_TRACK_ID = -1  # the game's own "unknown track" value

# "Session types" appendix
SESSION_TYPE_NAMES = {
    0: "Unknown", 1: "Practice 1", 2: "Practice 2", 3: "Practice 3", 4: "Short Practice",
    5: "Qualifying 1", 6: "Qualifying 2", 7: "Qualifying 3", 8: "Short Qualifying",
    9: "One-Shot Qualifying", 10: "Sprint Shootout 1", 11: "Sprint Shootout 2",
    12: "Sprint Shootout 3", 13: "Short Sprint Shootout", 14: "One-Shot Sprint Shootout",
    15: "Race", 16: "Race 2", 17: "Race 3", 18: "Time Trial",
}


@dataclass(frozen=True)
class SessionInfo:
    track_id: int  # -1 when the game reports no track
    track_length_m: int
    session_type: int
    formula: int

    @property
    def session_type_name(self):
        return SESSION_TYPE_NAMES.get(self.session_type, f"Session type {self.session_type}")


def parse_session(data):
    """Decode the circuit identity from a Session packet. Raises ValueError if too short."""
    if len(data) < PACKET_SIZE:
        raise ValueError(f"session packet too short: {len(data)} < {PACKET_SIZE} bytes")
    _weather, _track_temp, _air_temp, _laps, length, session_type, track_id, formula = (
        _PREFIX.unpack_from(data, HEADER_SIZE))
    return SessionInfo(track_id=track_id, track_length_m=length, session_type=session_type, formula=formula)
