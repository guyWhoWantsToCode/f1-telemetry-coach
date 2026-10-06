"""Parser for the F1 25 PacketCarTelemetryData packet (packet ID 6).

Layout comes from docs/f1_25_udp_spec_v3.pdf ("Car Telemetry Packet"): little endian,
packed, PacketHeader (29 bytes) + 22 x CarTelemetryData (60 bytes each) + 3 trailing
uint8/int8 fields = 1352 bytes. Only the fields up to m_revLightsPercent are decoded.
"""

import struct
from dataclasses import dataclass

from packet_header import HEADER_SIZE

CAR_TELEMETRY_PACKET_ID = 6
NUM_CARS = 22

# uint16 m_speed, float m_throttle, float m_steer, float m_brake, uint8 m_clutch,
# int8 m_gear, uint16 m_engineRPM, uint8 m_drs, uint8 m_revLightsPercent,
# uint16 m_revLightsBitValue, uint16 m_brakesTemperature[4],
# uint8 m_tyresSurfaceTemperature[4], uint8 m_tyresInnerTemperature[4],
# uint16 m_engineTemperature, float m_tyresPressure[4], uint8 m_surfaceType[4]
CAR_STRUCT = struct.Struct("<HfffBbHBBH4H4B4BH4f4B")
CAR_SIZE = CAR_STRUCT.size  # 60

PACKET_SIZE = HEADER_SIZE + NUM_CARS * CAR_SIZE + 3  # m_mfdPanelIndex, ...Secondary, m_suggestedGear
MIN_SIZE = HEADER_SIZE + NUM_CARS * CAR_SIZE  # everything we read


@dataclass(frozen=True)
class CarTelemetry:
    speed_kmh: int
    throttle: float  # 0.0 to 1.0
    steer: float  # -1.0 (full left) to 1.0 (full right)
    brake: float  # 0.0 to 1.0
    clutch: int  # 0 to 100
    gear: int  # -1 = reverse, 0 = neutral, 1-8
    engine_rpm: int
    drs: int  # 0 = off, 1 = on
    rev_lights_percent: int


def parse_car_telemetry(data, car_index):
    """Decode one car's telemetry from a full Car Telemetry packet.

    The caller must already have checked the header's packet ID is 6.
    Raises ValueError if the packet is too short or car_index is out of range.
    """
    if len(data) < MIN_SIZE:
        raise ValueError(f"car telemetry packet too short: {len(data)} < {MIN_SIZE} bytes")
    if not 0 <= car_index < NUM_CARS:
        raise ValueError(f"car index {car_index} out of range 0-{NUM_CARS - 1}")
    f = CAR_STRUCT.unpack_from(data, HEADER_SIZE + car_index * CAR_SIZE)
    return CarTelemetry(
        speed_kmh=f[0], throttle=f[1], steer=f[2], brake=f[3], clutch=f[4],
        gear=f[5], engine_rpm=f[6], drs=f[7], rev_lights_percent=f[8],
    )


def format_car_telemetry(t):
    gear = {-1: "R", 0: "N"}.get(t.gear, str(t.gear))
    return (
        f"speed={t.speed_kmh:3d} km/h  thr={t.throttle * 100:5.1f}%  brk={t.brake * 100:5.1f}%  "
        f"steer={t.steer:+.2f}  clutch={t.clutch:3d}  gear={gear}  rpm={t.engine_rpm:5d}  "
        f"drs={'ON' if t.drs else 'off'}  revlights={t.rev_lights_percent}%"
    )
