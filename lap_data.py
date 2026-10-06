"""Parser for the F1 25 PacketLapData packet (packet ID 2).

Layout comes from docs/f1_25_udp_spec_v3.pdf ("Lap Data Packet"): little endian, packed,
PacketHeader (29 bytes) + 22 x LapData (57 bytes each) + 2 trailing uint8 fields
(m_timeTrialPBCarIdx, m_timeTrialRivalCarIdx) = 1285 bytes. Only some fields are decoded.
"""

import struct
from dataclasses import dataclass

from packet_header import HEADER_SIZE

LAP_DATA_PACKET_ID = 2
NUM_CARS = 22

# uint32 m_lastLapTimeInMS, uint32 m_currentLapTimeInMS,
# uint16 m_sector1TimeMSPart, uint8 m_sector1TimeMinutesPart,
# uint16 m_sector2TimeMSPart, uint8 m_sector2TimeMinutesPart,
# uint16 m_deltaToCarInFrontMSPart, uint8 m_deltaToCarInFrontMinutesPart,
# uint16 m_deltaToRaceLeaderMSPart, uint8 m_deltaToRaceLeaderMinutesPart,
# float m_lapDistance, float m_totalDistance, float m_safetyCarDelta,
# uint8 m_carPosition, m_currentLapNum, m_pitStatus, m_numPitStops, m_sector,
# m_currentLapInvalid, m_penalties, m_totalWarnings, m_cornerCuttingWarnings,
# m_numUnservedDriveThroughPens, m_numUnservedStopGoPens, m_gridPosition,
# m_driverStatus, m_resultStatus, m_pitLaneTimerActive,
# uint16 m_pitLaneTimeInLaneInMS, uint16 m_pitStopTimerInMS,
# uint8 m_pitStopShouldServePen, float m_speedTrapFastestSpeed,
# uint8 m_speedTrapFastestLap
LAP_STRUCT = struct.Struct("<IIHBHBHBHBfff15BHHBfB")
LAP_SIZE = LAP_STRUCT.size  # 57

PACKET_SIZE = HEADER_SIZE + NUM_CARS * LAP_SIZE + 2
MIN_SIZE = HEADER_SIZE + NUM_CARS * LAP_SIZE  # everything we read

PIT_STATUS_NAMES = {0: "none", 1: "pitting", 2: "in pit area"}


@dataclass(frozen=True)
class LapData:
    current_lap_num: int
    current_lap_time_ms: int
    last_lap_time_ms: int  # 0 if no lap completed yet
    lap_distance: float  # metres, can be negative before the line is crossed
    total_distance: float  # metres, can be negative before the line is crossed
    sector: int  # 0 = sector 1, 1 = sector 2, 2 = sector 3 (as in the spec)
    sector1_time_ms: int
    sector2_time_ms: int
    car_position: int
    pit_status: int  # 0 = none, 1 = pitting, 2 = in pit area
    current_lap_invalid: int  # 0 = valid, 1 = invalid


def parse_lap_data(data, car_index):
    """Decode one car's lap data from a full Lap Data packet.

    The caller must already have checked the header's packet ID is 2.
    Raises ValueError if the packet is too short or car_index is out of range.
    """
    if len(data) < MIN_SIZE:
        raise ValueError(f"lap data packet too short: {len(data)} < {MIN_SIZE} bytes")
    if not 0 <= car_index < NUM_CARS:
        raise ValueError(f"car index {car_index} out of range 0-{NUM_CARS - 1}")
    f = LAP_STRUCT.unpack_from(data, HEADER_SIZE + car_index * LAP_SIZE)
    return LapData(
        last_lap_time_ms=f[0],
        current_lap_time_ms=f[1],
        sector1_time_ms=f[3] * 60000 + f[2],  # minutes part + ms part
        sector2_time_ms=f[5] * 60000 + f[4],
        lap_distance=f[10],
        total_distance=f[11],
        car_position=f[13],
        current_lap_num=f[14],
        pit_status=f[15],
        sector=f[17],
        current_lap_invalid=f[18],
    )


def format_lap_time(ms):
    """Milliseconds as M:SS.mmm (or '-' for 0, i.e. not set yet)."""
    if ms <= 0:
        return "-"
    minutes, rest = divmod(ms, 60000)
    return f"{minutes}:{rest / 1000:06.3f}"


def format_lap_data(d):
    return (
        f"lap={d.current_lap_num}  cur={format_lap_time(d.current_lap_time_ms)}  "
        f"last={format_lap_time(d.last_lap_time_ms)}  "
        f"dist={d.lap_distance:8.1f}m  total={d.total_distance:9.1f}m  "
        f"sector=S{d.sector + 1}  s1={format_lap_time(d.sector1_time_ms)}  "
        f"s2={format_lap_time(d.sector2_time_ms)}  pos={d.car_position}  "
        f"pit={PIT_STATUS_NAMES.get(d.pit_status, d.pit_status)}  "
        f"{'INVALID' if d.current_lap_invalid else 'valid'}"
    )
