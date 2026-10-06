import { Fragment } from 'react'
import type { RecordingStatus } from '../api/types'
import { Button } from '../design'
import './recording.css'
import { recordingView } from './view'

export interface RecordingControlProps {
  status: RecordingStatus | null
  reachable: boolean
  busy: boolean
  actionError: string | null
  onStart: () => void
  onStop: () => void
}

const SEGMENTS = [
  ['idle', 'Idle'],
  ['waiting', 'Waiting'],
  ['recording', 'Recording'],
] as const

/** Header instrument: IDLE · WAITING · RECORDING annunciator, readouts, and the Start/Stop switch. */
export function RecordingControl(props: RecordingControlProps) {
  const view = recordingView(props.status, props.reachable)
  const error = props.actionError ?? view.error
  const canStart = props.reachable && props.status !== null && !props.busy

  return (
    <div className="recording" role="group" aria-label="Telemetry recording">
      <span className="annunciator" role="status" aria-label={`Recording state: ${view.label}`}>
        {SEGMENTS.map(([state, text], i) => (
          <Fragment key={state}>
            {i > 0 && <span className="annunciator__sep" aria-hidden="true">&middot;</span>}
            <span
              className={`annunciator__seg annunciator__seg--${state}${view.state === state ? ' is-active' : ''}`}
              aria-current={view.state === state ? 'true' : undefined}
            >
              {text}
            </span>
          </Fragment>
        ))}
      </span>
      {view.state === 'error' && <span className="recording__flag">Error</span>}
      {view.state === 'offline' && <span className="recording__flag recording__flag--quiet">{view.label}</span>}
      {view.packets && <span className="recording__meta mono">{view.packets}</span>}
      {view.lap && <span className="recording__meta mono">{view.lap}</span>}
      {view.saved && <span className="recording__meta mono">{view.saved}</span>}
      {error && <span className="recording__error" title={error}>{error}</span>}
      {view.running ? (
        <Button size="sm" instrument onClick={props.onStop} disabled={props.busy}>Stop Recording</Button>
      ) : (
        <Button size="sm" instrument variant="primary" onClick={props.onStart} disabled={!canStart}>Start Recording</Button>
      )}
    </div>
  )
}
