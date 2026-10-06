"""Minimal UDP listener: checks that F1 telemetry from the Xbox reaches this PC."""

import socket
import time

from car_telemetry import CAR_TELEMETRY_PACKET_ID, format_car_telemetry, parse_car_telemetry
from packet_header import parse_header

HOST = "0.0.0.0"  # all local interfaces
PORT = 20777


def main():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.bind((HOST, PORT))
    except OSError as e:
        print(f"Could not bind to {HOST}:{PORT}: {e}")
        print("Is another program (or another copy of this script) using that port?")
        return

    sock.settimeout(1.0)  # lets Ctrl+C work and lets us report idle time
    print(f"Listening on UDP {HOST}:{PORT} (Ctrl+C to stop)...")

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
                # Only the player's Car Telemetry packets are printed; all packets are counted.
                try:
                    header = parse_header(data)
                    if header.packet_id == CAR_TELEMETRY_PACKET_ID:
                        car = parse_car_telemetry(data, header.player_car_index)
                        print(f"{ip} {len(data)}B ~{pps:.0f}pkt/s | {format_car_telemetry(car)}")
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
    finally:
        sock.close()


if __name__ == "__main__":
    main()
