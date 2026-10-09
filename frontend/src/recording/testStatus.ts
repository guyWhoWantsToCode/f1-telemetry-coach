import type { RecordingStatus } from '../api/types'

/** A recording status for tests; override only what a test cares about. */
export function makeStatus(overrides: Partial<RecordingStatus> = {}): RecordingStatus {
  return {
    state: 'idle',
    running: false,
    receiving: false,
    packets_per_second: 0,
    packets_total: 0,
    session_uid: null,
    current_lap: null,
    laps_saved: 0,
    saved_laps: [],
    unmatched_samples: 0,
    motion_packets: 0,
    parse_errors: 0,
    last_error: null,
    port: 20777,
    started_at: null,
    active_track_id: null,
    active_track_name: null,
    active_track_known: null,
    track_length_m: null,
    session_type: null,
    session_type_name: null,
    track_error: null,
    ...overrides,
  }
}
