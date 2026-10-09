import type { RecordingStatus, TracksResponse, TrackSummary } from '../api/types'
import { findTrack, parseViewing, trackOptions, UNASSIGNED, type Viewing } from '../lib/tracks'
import './trackbar.css'

export interface TrackBarProps {
  tracks: TracksResponse | null
  loading: boolean
  error: string | null
  /** The circuit whose history is shown. Chosen here; it never changes the live circuit. */
  viewing: Viewing | null
  onView: (viewing: Viewing) => void
  /** Live recording status. `active_track_*` comes from the game's Session packets, not from the UI. */
  recording: RecordingStatus | null
}

function plural(n: number, one: string, many = `${one}s`) {
  return `${n} ${n === 1 ? one : many}`
}

function historyText(track: TrackSummary): string {
  const { stats } = track
  const parts: string[] = []
  parts.push(stats.pb ? `PB ${stats.pb.lap_time}` : 'no PB')
  parts.push(plural(stats.valid_laps, 'valid lap'))
  parts.push(plural(stats.sessions, 'session'))
  if (track.has_corner_distances) parts.push(plural(track.corner_count, 'corner'))
  else if (track.has_corner_metadata) parts.push(`${plural(track.corner_count, 'corner')} (distances not calibrated)`)
  else parts.push('no corner data')
  return parts.join(' · ')
}

function LiveCircuit({ recording }: { recording: RecordingStatus | null }) {
  if (recording === null || !recording.running) return <span className="trackbar__value text-dim">not recording</span>
  if (recording.active_track_id === null) return <span className="trackbar__value text-muted">waiting for session data</span>
  return (
    <span className="trackbar__value">
      {recording.active_track_name ?? `Track ${recording.active_track_id}`}
      {recording.track_length_m ? <span className="text-dim mono"> {recording.track_length_m} m</span> : null}
      {recording.session_type_name ? <span className="text-dim"> {recording.session_type_name}</span> : null}
    </span>
  )
}

/** Compact circuit row: what is being viewed (selectable) next to what the game says is live. */
export function TrackBar(props: TrackBarProps) {
  const { tracks, viewing, recording } = props
  const live = recording?.running ? recording.active_track_id : null
  const viewed = findTrack(tracks, viewing)
  const differs = live !== null && viewing !== null && viewing !== live
  const options = tracks ? trackOptions({ ...tracks, active_track_id: live }) : []

  let history: string
  if (props.error) history = props.error
  else if (props.loading && tracks === null) history = 'Loading circuits...'
  else if (viewing === UNASSIGNED) {
    history = `${plural(tracks?.unassigned_laps ?? 0, 'lap')} recorded before circuit identification: assign each to a circuit`
  } else if (viewed) history = historyText(viewed)
  else history = options.length === 0 ? 'No circuits yet: a circuit appears once the game reports it during a recording' : ''

  return (
    <div className="trackbar" role="group" aria-label="Circuit">
      <div className="trackbar__group">
        <span className="trackbar__label">Viewing</span>
        <select
          className="select trackbar__select"
          aria-label="Circuit being viewed"
          value={viewing === null ? '' : String(viewing)}
          disabled={options.length === 0}
          onChange={(e) => props.onView(parseViewing(e.target.value))}
        >
          {viewing === null && <option value="">No circuits</option>}
          {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
        <span className={`trackbar__meta mono${props.error ? ' text-warn' : ''}`}>{history}</span>
      </div>
      <div className="trackbar__group trackbar__live" aria-label="Live circuit">
        <span className="trackbar__label">Live</span>
        <LiveCircuit recording={recording} />
        {differs && <span className="trackbar__flag" role="status">viewing a different circuit than the live session</span>}
      </div>
    </div>
  )
}
