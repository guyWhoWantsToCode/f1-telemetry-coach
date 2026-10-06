"""Records the player's laps to CSV by combining Car Telemetry and Lap Data samples.

Feed it decoded packets for the player's car only:
    recorder.on_telemetry(CarTelemetry, frame_id)
    recorder.on_lap_data(session_uid, LapData, frame_id)   # return the saved Path, or None

The spec guarantees Lap Data and Car Telemetry for a frame are sent together on that frame,
so when frame_id (the header's m_overallFrameIdentifier, which never rewinds after a
flashback) is given, each Lap Data packet is paired with the telemetry of the SAME frame,
whichever of the two arrives first. Without frame_id the most recent telemetry is used.

A sample is taken whenever the lap distance has advanced SAMPLE_SPACING_M beyond the last
saved sample. A lap is only
recorded if it was seen from the start (first sample within START_WINDOW_M of the line),
so joining mid-lap or leaving the pits mid-lap never produces a partial file.
"""

import csv
from pathlib import Path

SAMPLE_SPACING_M = 5.0
START_WINDOW_M = 50.0  # a lap must be first seen this close to the line to be recorded
MIN_ROWS = 10  # shorter laps (e.g. a reset right after the line) are discarded
FRAMES_KEPT = 8  # recent telemetry frames remembered for frame matching
LAP_TIME_WAIT_PACKETS = 30  # wait this many Lap Data packets for the last-lap time to update

CSV_COLUMNS = [
    "lap", "lap_distance_m", "lap_time_ms", "speed_kmh", "throttle", "brake",
    "steer", "gear", "engine_rpm", "drs", "invalid",
]


def format_lap_time_for_filename(ms):
    if not ms:
        return "unknown"
    minutes, rest = divmod(ms, 60000)
    return f"{minutes}m{rest / 1000:06.3f}s"


class LapRecorder:
    def __init__(self, out_dir="data/laps"):
        self.out_dir = Path(out_dir)
        self._telemetry = None  # latest telemetry (used when no frame id is given)
        self._by_frame = {}  # frame id -> telemetry, newest last
        self._waiting = None  # (session_uid, frame_id, lap) still waiting for its telemetry
        self.unmatched_samples = 0  # lap packets whose frame's telemetry never arrived
        self._reset_session(None)

    def _reset_session(self, session_uid):
        self._session_uid = session_uid
        self._lap_num = None
        self._rows = []  # rows of the lap in progress
        self._recording = False
        self._invalid = False
        self._last_distance = None
        self._seen_last_lap_ms = None  # most recent last-lap time reported by the game
        self._prev_last_lap_ms = None  # last-lap time reported before the current lap began
        self._pending = None  # finished lap waiting for its lap time: (lap_num, rows, invalid)
        self._pending_packets = 0

    def on_telemetry(self, telemetry, frame_id=None):
        self._telemetry = telemetry
        if frame_id is None:
            return None
        self._by_frame[frame_id] = telemetry
        if len(self._by_frame) > FRAMES_KEPT:
            del self._by_frame[next(iter(self._by_frame))]
        if self._waiting and self._waiting[1] == frame_id:  # lap packet arrived first
            session_uid, _, lap = self._waiting
            self._waiting = None
            return self._process(session_uid, lap, telemetry)
        return None

    def on_lap_data(self, session_uid, lap, frame_id=None):
        if frame_id is None:
            return self._process(session_uid, lap, self._telemetry)
        saved = None
        if self._waiting:  # its telemetry never showed up: still run lap bookkeeping
            old_session, _, old_lap = self._waiting
            self._waiting = None
            self.unmatched_samples += 1
            saved = self._process(old_session, old_lap, None)
        telemetry = self._by_frame.get(frame_id)
        if telemetry is None:
            self._waiting = (session_uid, frame_id, lap)  # telemetry may arrive after it
            return saved
        return self._process(session_uid, lap, telemetry) or saved

    def _process(self, session_uid, lap, telemetry):
        saved = None
        if session_uid != self._session_uid:
            saved = self._write_pending(None)  # don't lose a finished lap of the old session
            self._reset_session(session_uid)

        if lap.current_lap_num != self._lap_num:
            if self._recording and len(self._rows) >= MIN_ROWS:
                saved = self._write_pending(None) or saved
                self._pending = (self._lap_num, self._rows, self._invalid)
                self._pending_packets = 0
            self._prev_last_lap_ms = self._seen_last_lap_ms
            self._start_lap(lap)

        # A finished lap is written once the game reports its time (last lap time changes).
        if self._pending and lap.last_lap_time_ms != self._prev_last_lap_ms:
            saved = self._write_pending(lap.last_lap_time_ms) or saved

        if self._recording:
            self._maybe_sample(lap, telemetry)
        if self._pending:
            self._pending_packets += 1
            if self._pending_packets >= LAP_TIME_WAIT_PACKETS:
                saved = self._write_pending(None) or saved  # time never updated: name it "unknown"
        self._seen_last_lap_ms = lap.last_lap_time_ms
        return saved

    def _start_lap(self, lap):
        self._lap_num = lap.current_lap_num
        self._rows = []
        self._invalid = False
        self._last_distance = None
        # Only record laps we see begin at the line, not ones joined mid-lap.
        self._recording = lap.lap_distance <= START_WINDOW_M

    def _maybe_sample(self, lap, telemetry):
        if telemetry is None or lap.pit_status != 0 or lap.lap_distance < 0:
            return  # in the pits, before the line, or no telemetry yet
        self._invalid = self._invalid or bool(lap.current_lap_invalid)  # sticky for the lap
        if self._last_distance is not None and lap.lap_distance < self._last_distance + SAMPLE_SPACING_M:
            return  # too close to the last sample (or moving backwards, e.g. flashback)
        t = telemetry
        self._rows.append([
            lap.current_lap_num, round(lap.lap_distance, 2), lap.current_lap_time_ms,
            t.speed_kmh, round(t.throttle, 4), round(t.brake, 4), round(t.steer, 4),
            t.gear, t.engine_rpm, t.drs, int(self._invalid),
        ])
        self._last_distance = lap.lap_distance

    def _write_pending(self, lap_time_ms):
        if not self._pending:
            return None
        lap_num, rows, invalid = self._pending
        self._pending = None
        if invalid:  # make the invalid flag consistent across the whole saved lap
            for row in rows:
                row[-1] = 1
        name = (f"{self._session_uid:016x}_lap{lap_num:02d}_"
                f"{format_lap_time_for_filename(lap_time_ms)}{'_invalid' if invalid else ''}.csv")
        self.out_dir.mkdir(parents=True, exist_ok=True)
        path = self.out_dir / name
        with open(path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(CSV_COLUMNS)
            writer.writerows(rows)
        return path
