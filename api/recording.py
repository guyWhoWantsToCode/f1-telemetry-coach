"""Background recording of F1 25 UDP telemetry, controlled from the API.

Owns the lifecycle of at most one recording: bind the UDP socket, run a worker thread
that feeds packets to the existing parsers and LapRecorder, and release the socket when
stopped. The parsing and recording logic is not reimplemented here.

Like the command-line recorder, a lap that is still in progress when recording stops is
not saved: only laps seen from the start line to the next lap are written.
"""

import socket
import threading
import time
from collections import deque

from car_telemetry import CAR_TELEMETRY_PACKET_ID, parse_car_telemetry
from lap_data import LAP_DATA_PACKET_ID, parse_lap_data
from lap_recorder import LapRecorder
from motion_packet import MOTION_PACKET_ID, parse_player_position
from packet_header import parse_header
from session_packet import SESSION_PACKET_ID, UNKNOWN_TRACK_ID, parse_session
from udp_listener import HOST, PORT  # the same listening configuration as the CLI

IDLE = "idle"  # not recording
WAITING = "waiting"  # listening, but no packets are arriving
RECORDING = "recording"  # listening and packets are arriving
ERROR = "error"  # failed to start, or the worker crashed

RECEIVE_BUFFER_BYTES = 4 * 1024 * 1024
RECEIVE_TIMEOUT_S = 0.2  # socket poll interval; bounds how long stop() takes
STOP_JOIN_TIMEOUT_S = 3.0
RECENT_SAVES_KEPT = 50


class RecordingBusyError(RuntimeError):
    """A recording is already running."""


class RecordingStartError(RuntimeError):
    """The UDP socket could not be opened."""


class RecordingService:
    def __init__(self, out_dir, host=HOST, port=PORT, idle_after_s=2.0, tracks=None, positions_dir=None):
        self.out_dir = out_dir
        self.positions_dir = positions_dir  # where per-lap world positions are saved (None = not recorded)
        self.tracks = tracks  # optional TrackService: remembers circuits, laps and learned events
        self.host = host
        self.port = port
        self.idle_after_s = idle_after_s  # no packet for this long = "not receiving"
        self._lock = threading.Lock()
        self._thread = None
        self._stop_event = None
        self._error_state = False
        self._last_error = None
        self._reset_stats()

    def _reset_stats(self):
        self._started_at = None
        self._packets_total = 0
        self._pps = 0.0
        self._last_packet_at = None
        self._session_uid = None
        self._current_lap = None
        self._saved = deque(maxlen=RECENT_SAVES_KEPT)
        self._saved_count = 0
        self._unmatched = 0
        self._parse_errors = 0
        self._motion_packets = 0  # Motion packets whose player position was decoded
        self._active_track = None  # the circuit the game reports right now (from Session packets)
        self._session_key = None  # last (session, track, length, type) seen: repeats are ignored
        self._session_tracks = {}  # session UID -> (SessionInfo, packet format)
        self._track_error = None

    # ------------------------------------------------------------------ control

    @property
    def running(self):
        thread = self._thread
        return thread is not None and thread.is_alive()

    def start(self):
        """Bind the UDP port and start recording in the background. Returns immediately."""
        with self._lock:
            if self.running:
                raise RecordingBusyError("a recording is already running")
            self._reset_stats()
            self._error_state = False
            self._last_error = None
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                sock.bind((self.host, self.port))
            except OSError as e:
                sock.close()
                self._error_state = True
                self._last_error = (f"cannot listen on UDP port {self.port}: {e}. "
                                    "Is another listener (e.g. udp_listener.py) running?")
                raise RecordingStartError(self._last_error) from e
            try:  # headroom for bursts at 600+ packets/s so the OS does not drop packets while we work
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, RECEIVE_BUFFER_BYTES)
            except OSError:
                pass
            sock.settimeout(RECEIVE_TIMEOUT_S)
            self.port = sock.getsockname()[1]  # the real port when 0 was requested
            self._started_at = time.time()
            self._stop_event = threading.Event()
            self._thread = threading.Thread(
                target=self._run, args=(sock, LapRecorder(self.out_dir, self.positions_dir), self._stop_event),
                name="udp-recorder", daemon=True)
            self._thread.start()

    def stop(self):
        """Stop recording and release the socket. Safe to call when idle."""
        with self._lock:
            thread, event = self._thread, self._stop_event
            self._error_state = False  # an explicit stop acknowledges a previous error
        if thread is not None:
            event.set()
            thread.join(STOP_JOIN_TIMEOUT_S)

    # ------------------------------------------------------------------- status

    def status(self):
        with self._lock:
            now = time.monotonic()
            running = self.running
            receiving = (running and self._last_packet_at is not None
                         and now - self._last_packet_at < self.idle_after_s)
            if running:
                state = RECORDING if receiving else WAITING
            else:
                state = ERROR if self._error_state else IDLE
            return {
                "state": state,
                "running": running,
                "receiving": bool(receiving),
                "packets_per_second": round(self._pps, 1) if receiving else 0.0,
                "packets_total": self._packets_total,
                "session_uid": f"{self._session_uid:016x}" if self._session_uid is not None else None,
                "current_lap": self._current_lap,
                "laps_saved": self._saved_count,
                "saved_laps": list(self._saved),
                "unmatched_samples": self._unmatched,
                "motion_packets": self._motion_packets,
                "parse_errors": self._parse_errors,
                "last_error": self._last_error,
                "port": self.port,
                "started_at": self._started_at,
                **self._track_status(),
            }

    def _track_status(self):
        track = self._active_track
        return {
            "active_track_id": track["track_id"] if track else None,
            "active_track_name": track["name"] if track else None,
            "active_track_known": track["known"] if track else None,
            "track_length_m": track["length"] if track else None,
            "session_type": track["session_type"] if track else None,
            "session_type_name": track["session_type_name"] if track else None,
            "track_error": self._track_error,
        }

    # ------------------------------------------------------------------- worker

    def _run(self, sock, recorder, stop_event):
        window_start, window_count = time.monotonic(), 0
        try:
            while not stop_event.is_set():
                try:
                    data, _addr = sock.recvfrom(65535)
                except socket.timeout:
                    data = None
                except ConnectionResetError:
                    continue  # Windows can raise this on UDP; safe to ignore

                if data is not None:
                    window_count += 1
                    self._handle_packet(data, recorder)

                now = time.monotonic()
                if now - window_start >= 1.0:
                    with self._lock:
                        self._pps = window_count / (now - window_start)
                    window_start, window_count = now, 0
        except Exception as e:  # keep the API alive; report instead of dying silently
            with self._lock:
                self._error_state = True
                self._last_error = f"recording stopped unexpectedly: {e}"
        finally:
            sock.close()  # always release the UDP port

    def _handle_packet(self, data, recorder):
        """Dispatch one packet to the existing parsers and recorder (player's car only)."""
        try:
            header = parse_header(data)
            with self._lock:
                self._packets_total += 1
                self._last_packet_at = time.monotonic()
            if header.packet_id == SESSION_PACKET_ID:
                self._on_session(header, parse_session(data))
                return
            if header.packet_id == MOTION_PACKET_ID:
                position = parse_player_position(data, header.player_car_index)
                recorder.on_motion(position, header.overall_frame_identifier)
                with self._lock:
                    self._motion_packets += 1
                return
            if header.packet_id == CAR_TELEMETRY_PACKET_ID:
                telemetry = parse_car_telemetry(data, header.player_car_index)
                saved = recorder.on_telemetry(telemetry, header.overall_frame_identifier)
                lap_number = None
            elif header.packet_id == LAP_DATA_PACKET_ID:
                lap = parse_lap_data(data, header.player_car_index)
                saved = recorder.on_lap_data(header.session_uid, lap, header.overall_frame_identifier)
                lap_number = lap.current_lap_num
            else:
                return
        except ValueError:
            with self._lock:
                self._parse_errors += 1
            return
        with self._lock:
            self._session_uid = header.session_uid
            if lap_number is not None:
                self._current_lap = lap_number
            self._unmatched = recorder.unmatched_samples
            if saved:
                self._saved.append(saved.stem)
                self._saved_count += 1
        if saved:
            self._register_saved_lap(saved)

    def _on_session(self, header, info):
        """A Session packet (about twice a second): learn which circuit is active. Repeats of the
        same session/circuit do nothing; a different circuit switches the active track at once."""
        key = (header.session_uid, info.track_id, info.track_length_m, info.session_type)
        with self._lock:
            if key == self._session_key:
                return
            self._session_key = key
            self._session_tracks[header.session_uid] = (info, header.packet_format)
        ident, error = None, None
        if info.track_id != UNKNOWN_TRACK_ID and self.tracks is not None:
            try:
                ident = self.tracks.activate(info, header.packet_format)
            except Exception as e:  # a track-memory problem must never stop the recording
                error = f"track memory error: {e}"
        with self._lock:
            self._track_error = error
            self._session_uid = header.session_uid
            if info.track_id == UNKNOWN_TRACK_ID:
                self._active_track = None  # the game reports no circuit
            else:
                self._active_track = {
                    "track_id": info.track_id,
                    "name": ident["name"] if ident else None,
                    "known": ident["known"] if ident else None,
                    "length": info.track_length_m,
                    "session_type": info.session_type,
                    "session_type_name": info.session_type_name,
                }

    def _register_saved_lap(self, saved):
        """Tag a just-saved lap with the circuit its session was on (looked up by session UID)."""
        if self.tracks is None:
            return
        try:
            uid = int(saved.stem.split("_")[0], 16)
        except ValueError:
            return
        with self._lock:
            entry = self._session_tracks.get(uid)
        if entry is None or entry[0].track_id == UNKNOWN_TRACK_ID:
            return  # no Session packet seen for that session: the lap stays "track unknown"
        try:
            self.tracks.register_recorded_lap(saved.stem, entry[0], entry[1])
        except Exception as e:
            with self._lock:
                self._track_error = f"track memory error: {e}"
