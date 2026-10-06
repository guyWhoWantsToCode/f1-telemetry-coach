import type { RecordingState, RecordingStatus } from '../api/types'

export interface RecordingView {
  state: RecordingState | 'offline'
  label: string
  /** "Receiving 612 pkt/s" / "No packets"; null when not listening. */
  packets: string | null
  lap: string | null
  saved: string | null
  error: string | null
  running: boolean
}

const LABELS: Record<RecordingState, string> = {
  idle: 'Idle',
  waiting: 'Waiting for packets',
  recording: 'Recording',
  error: 'Error',
}

/** Display text for a recording status. `status` is null before the first reply. */
export function recordingView(status: RecordingStatus | null, reachable = true): RecordingView {
  if (!reachable || status === null) {
    return { state: 'offline', label: reachable ? 'Checking' : 'API offline', packets: null, lap: null, saved: null, error: null, running: false }
  }
  const packets = status.running
    ? status.receiving ? `Receiving ${Math.round(status.packets_per_second)} pkt/s` : 'No packets'
    : null
  return {
    state: status.state,
    label: LABELS[status.state],
    packets,
    lap: status.running && status.current_lap !== null ? `Lap ${status.current_lap}` : null,
    saved: status.running || status.laps_saved > 0 ? `${status.laps_saved} saved` : null,
    error: status.last_error,
    running: status.running,
  }
}
