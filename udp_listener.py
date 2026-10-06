"""Minimal UDP listener: checks that F1 telemetry from the Xbox reaches this PC."""

import socket
import time

from packet_header import format_header, parse_header

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
                line = f"From {ip}  size={len(data)} bytes  ~{pps:.0f} pkt/s"
                try:
                    line += "  | " + format_header(parse_header(data))
                except ValueError as e:
                    line += f"  | header error: {e}"
                print(line)

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
