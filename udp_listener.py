"""Minimal UDP listener: checks that F1 telemetry from the Xbox reaches this PC."""

import argparse
import socket
import time

from car_telemetry import CAR_TELEMETRY_PACKET_ID, format_car_telemetry, parse_car_telemetry
from lap_data import LAP_DATA_PACKET_ID, format_lap_data, parse_lap_data
from lap_recorder import LapRecorder
from packet_header import parse_header

HOST = "0.0.0.0"  # all local interfaces
PORT = 20777

# What --show prints: (packet ID, parser, formatter). Only the player's car is decoded.
MODES = {
    "telemetry": (CAR_TELEMETRY_PACKET_ID, parse_car_telemetry, format_car_telemetry),
    "lap": (LAP_DATA_PACKET_ID, parse_lap_data, format_lap_data),
}


def main():
    arg_parser = argparse.ArgumentParser(description="Listen for F1 25 UDP telemetry.")
    arg_parser.add_argument("--show", choices=MODES,
                            help="which decoded packets to print (default: telemetry, "
                                 "or nothing when --record is used)")
    arg_parser.add_argument("--record", action="store_true",
                            help="save each completed lap to data/laps/ as CSV")
    args = arg_parser.parse_args()
    show = args.show or (None if args.record else "telemetry")
    recorder = LapRecorder() if args.record else None

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.bind((HOST, PORT))
    except OSError as e:
        print(f"Could not bind to {HOST}:{PORT}: {e}")
        print("Is another program (or another copy of this script) using that port?")
        return

    sock.settimeout(1.0)  # lets Ctrl+C work and lets us report idle time
    print(f"Listening on UDP {HOST}:{PORT} (Ctrl+C to stop)...")
    if recorder:
        print("Recording laps to data/laps/ ...")

    count = 0
    window_start = time.monotonic()
    pps = 0.0

    try:
        while True:
            try:
                data, (ip, _port) = sock.recvfrom(65535)
            except socket.timeout:
                data = None
            except ConnectionResetError:
                continue  # Windows can raise this on UDP; safe to ignore

            if data is not None:
                count += 1
                # Only the player's car is decoded; all packets are counted.
                try:
                    header = parse_header(data)
                    for name, (packet_id, parse, fmt) in MODES.items():
                        if header.packet_id != packet_id:
                            continue
                        if show != name and recorder is None:
                            continue
                        decoded = parse(data, header.player_car_index)
                        if show == name:
                            print(f"{ip} {len(data)}B ~{pps:.0f}pkt/s | {fmt(decoded)}")
                        if recorder:
                            frame = header.overall_frame_identifier
                            if name == "telemetry":
                                saved = recorder.on_telemetry(decoded, frame)
                            else:
                                saved = recorder.on_lap_data(header.session_uid, decoded, frame)
                            if saved:
                                print(f"Saved lap: {saved}")
                except ValueError as e:
                    print(f"{ip} {len(data)}B parse error: {e}")

            now = time.monotonic()
            if now - window_start >= 1.0:
                pps = count / (now - window_start)
                if data is None:
                    print("... no packets in the last second")
                count = 0
                window_start = now
    except KeyboardInterrupt:
        print("\nStopped.")
        if recorder:
            print(f"Lap packets without matching-frame telemetry: {recorder.unmatched_samples}")
    finally:
        sock.close()


if __name__ == "__main__":
    main()
