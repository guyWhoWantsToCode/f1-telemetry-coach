import { useEffect } from 'react'
import { getLapPath, getTrackMap } from '../api/client'
import type { RecordingStatus } from '../api/types'
import type { CursorStore } from '../charts/cursorStore'
import { Notice, Panel, Placeholder } from '../design'
import { useAsyncAction } from '../hooks/useAsyncAction'
import { TrackMap } from './TrackMap'

const loadMap = (signal: AbortSignal, trackId: number) => getTrackMap(trackId, signal)
const loadLapPath = (signal: AbortSignal, lapId: string) => getLapPath(lapId, signal)

export interface MapPanelProps {
  /** The circuit being viewed. Maps are per circuit: nothing from another circuit is ever shown. */
  trackId: number
  refLapId: string | null
  cmpLapId: string | null
  store: CursorStore
  distances: number[] | null
  /** Changes whenever laps are added, so the circuit trace is re-read. */
  version: number
  /** Live recording status, used to explain why newly recorded laps may have no positions. */
  recording: RecordingStatus | null
}

/** Track map panel with its loading, error and empty states. Never draws a made-up circuit. */
export function MapPanel(props: MapPanelProps) {
  const { trackId, refLapId, cmpLapId, version } = props
  const map = useAsyncAction(loadMap)
  const ref = useAsyncAction(loadLapPath)
  const cmp = useAsyncAction(loadLapPath)
  const { run: fetchMap } = map
  const { run: fetchRef, reset: resetRef } = ref
  const { run: fetchCmp, reset: resetCmp } = cmp

  useEffect(() => {
    void fetchMap(trackId)
  }, [fetchMap, trackId, version])
  useEffect(() => {
    if (refLapId) void fetchRef(refLapId)
    else resetRef()
  }, [fetchRef, resetRef, refLapId])
  useEffect(() => {
    if (cmpLapId) void fetchCmp(cmpLapId)
    else resetCmp()
  }, [fetchCmp, resetCmp, cmpLapId])

  const geometry = map.state.status === 'ready' ? map.state.data : null
  const refPath = ref.state.status === 'ready' ? ref.state.data : null
  const cmpPath = cmp.state.status === 'ready' ? cmp.state.data : null
  const anything = !!geometry?.available || !!refPath?.available || !!cmpPath?.available
  const loading = [map, ref, cmp].some((a) => a.state.status === 'loading')
  const failed = [map, ref, cmp].find((a) => a.state.status === 'error')

  const noMotion = props.recording?.running && props.recording.motion_packets === 0 && props.recording.packets_total > 50

  let body
  if (failed && failed.state.status === 'error' && !anything) {
    body = <div className="panel__body"><Notice tone="error" title="Could not load the track map">{failed.state.error}</Notice></div>
  } else if (!anything && loading) {
    body = <Placeholder>Loading track map...</Placeholder>
  } else if (!anything) {
    body = (
      <Placeholder>
        <div>No position data for this circuit yet, so there is no map to draw.</div>
        <div className="text-dim">
          {geometry && geometry.reason === 'no_usable_laps'
            ? geometry.message
            : 'Positions come from the game’s Motion packets and are saved with each lap you record. Record a new valid lap with the recording control: laps recorded before this feature have none.'}
        </div>
        {geometry && geometry.rejected.length > 0 && (
          <ul>{geometry.rejected.map((r) => <li key={r.lap_id}>{r.lap_id}: {r.reason}</li>)}</ul>
        )}
      </Placeholder>
    )
  } else {
    body = (
      <TrackMap
        key={`${trackId}:${refLapId}:${cmpLapId}:${geometry?.available ? geometry.laps.length : 0}`}
        geometry={geometry}
        refPath={refPath}
        cmpPath={cmpPath}
        store={props.store}
        distances={props.distances}
      />
    )
  }

  return (
    <Panel title="Track map" flush surface="plot">
      {noMotion && (
        <div className="panel__body">
          <Notice tone="warn" title="No Motion packets are arriving">
            Laps recorded now will have no positions. Check that UDP telemetry is on in the game.
          </Notice>
        </div>
      )}
      {body}
    </Panel>
  )
}
