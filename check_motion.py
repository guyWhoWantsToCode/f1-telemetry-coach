"""Check what the game sends before relying on the track map (nothing is saved).

    python check_motion.py [seconds]

Listens on UDP 20777 (stop the recording first: only one program can use the port) and reports
how many packets of each kind arrive and, from the Motion packets, the X/Y/Z extent of the
player's car. While you drive a lap, the vertical axis (expected: Y) should span far less than
the other two. The map code checks this itself and shows whether it was confirmed.
"""

import collections
import socket
import sys
import time

from motion_packet import MOTION_PACKET_ID, parse_player_position
from packet_header import PACKET_NAMES, parse_header
from session_packet import SESSION_PACKET_ID, parse_session
from udp_listener import HOST, PORT


def main(seconds=8.0):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.bind((HOST, PORT))
    except OSError as e:
        print(f"Cannot listen on UDP {PORT}: {e}\nStop the recording (or udp_listener.py) first.")
        return 1
    sock.settimeout(0.5)
    print(f"Listening on UDP {PORT} for {seconds:.0f} s: drive while this runs...")
    counts, positions, session = collections.Counter(), [], None
    end = time.time() + seconds
    try:
        while time.time() < end:
            try:
                data, _ = sock.recvfrom(65535)
            except socket.timeout:
                continue
            try:
                header = parse_header(data)
                counts[header.packet_id] += 1
                if header.packet_id == MOTION_PACKET_ID:
                    p = parse_player_position(data, header.player_car_index)
                    positions.append((p.x, p.y, p.z))
                elif header.packet_id == SESSION_PACKET_ID and session is None:
                    session = parse_session(data)
            except ValueError:
                continue
    finally:
        sock.close()

    if not counts:
        print("No packets received. Is UDP telemetry on, with this PC's IP and port 20777?")
        return 1
    print("Packets received:", ", ".join(f"{PACKET_NAMES.get(i, i)} x{n}" for i, n in sorted(counts.items())))
    if session:
        print(f"Session: track ID {session.track_id}, length {session.track_length_m} m, {session.session_type_name}")
    if not positions:
        print("No Motion packets: the map cannot be recorded from this setup.")
        return 1
    xs, ys, zs = zip(*positions)
    spans = {"X": max(xs) - min(xs), "Y": max(ys) - min(ys), "Z": max(zs) - min(zs)}
    print(f"Motion samples: {len(positions)}")
    for axis, values in (("X", xs), ("Y", ys), ("Z", zs)):
        print(f"  {axis}: {min(values):9.1f} .. {max(values):9.1f} m   (span {spans[axis]:.1f} m)")
    smallest = min(spans, key=spans.get)
    print(f"Smallest extent: {smallest}" + (" (as expected for the vertical axis)" if smallest == "Y"
          else " (NOT Y: tell me, the map assumes Y is vertical)"))
    return 0


if __name__ == "__main__":
    sys.exit(main(float(sys.argv[1]) if len(sys.argv) > 1 else 8.0))
