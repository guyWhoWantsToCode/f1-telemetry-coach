import { useCallback, useEffect, useMemo, useState } from 'react'
import { API_BASE, assignLapTrack, compareLaps, errorMessage, getComparison, getEvents, getLaps, getTrackCatalog, getTracks } from '../../api/client'
import type { LapMeta } from '../../api/types'
import { createCursorStore } from '../../charts/cursorStore'
import { TelemetryPanel } from '../../charts/TelemetryPanel'
import { Button, Checkbox, Notice, Panel, Placeholder } from '../../design'
import { useAsyncAction } from '../../hooks/useAsyncAction'
import { MapPanel } from '../../map/MapPanel'
import { chooseViewing, isViewable, lapsFor, UNASSIGNED, type Viewing } from '../../lib/tracks'
import { RecordingControl } from '../../recording/RecordingControl'
import { useRecording } from '../../recording/useRecording'
import { TrackBar } from '../../tracks/TrackBar'
import { EventsTable } from './EventsTable'
import { LapTable } from './LapTable'
import { Summary } from './Summary'
import './page.css'

const NO_LAPS: LapMeta[] = []

// Adapters with a stable identity: the hook passes the abort signal first.
const loadLaps = (signal: AbortSignal) => getLaps(signal)
const runCompare = (signal: AbortSignal, ref: string, cmp: string, allowInvalid: boolean) =>
  compareLaps(ref, cmp, allowInvalid, signal)
const loadEvents = (signal: AbortSignal, comparisonId: string) => getEvents(comparisonId, signal)
const loadComparison = (signal: AbortSignal, comparisonId: string) => getComparison(comparisonId, signal)
const loadTracks = (signal: AbortSignal) => getTracks(signal)
const loadCatalog = (signal: AbortSignal) => getTrackCatalog(signal)

/** Starting selection from the real laps: fastest valid lap as reference, next lap as comparison. */
function defaultSelection(laps: LapMeta[]): { ref: string | null; cmp: string | null } {
  const timed = laps.filter((l) => l.valid && l.lap_time_ms !== null)
  const best = timed.sort((a, b) => (a.lap_time_ms ?? 0) - (b.lap_time_ms ?? 0))[0] ?? laps[0]
  if (!best) return { ref: null, cmp: null }
  const others = laps.filter((l) => l.id !== best.id)
  const next = others.find((l) => l.valid) ?? others[0]
  return { ref: best.id, cmp: next?.id ?? null }
}

/** One selected lap in the comparison panel; the swatch matches its trace color in the charts. */
function SelectedLap({ role, lap }: { role: 'ref' | 'cmp'; lap: LapMeta | undefined }) {
  return (
    <div className="selected-lap">
      <span className="selected-lap__swatch" style={{ background: `var(--chart-${role})` }} />
      <span className="selected-lap__role">{role === 'ref' ? 'Reference' : 'Comparison'}</span>
      {lap ? (
        <>
          <span className="selected-lap__lap mono">Lap {lap.lap_number}</span>
          <span className="selected-lap__time mono">{lap.lap_time ?? '—'}</span>
          <span className={`status ${lap.valid ? 'status--valid' : 'status--invalid'}`}>{lap.valid ? 'Valid' : 'Invalid'}</span>
        </>
      ) : (
        <span className="text-dim">not selected</span>
      )}
    </div>
  )
}

export default function LapComparisonPage() {
  const laps = useAsyncAction(loadLaps)
  const compare = useAsyncAction(runCompare)
  const events = useAsyncAction(loadEvents)
  const detail = useAsyncAction(loadComparison)
  const [sel, setSel] = useState<{ ref: string | null; cmp: string | null } | null>(null) // the user's lap choice
  const [allowInvalid, setAllowInvalid] = useState(false)

  const cursorStore = useMemo(() => createCursorStore(), []) // chart cursor, shared with the track map
  const tracks = useAsyncAction(loadTracks)
  const catalog = useAsyncAction(loadCatalog)
  const [pickedViewing, setPickedViewing] = useState<Viewing | null>(null) // set once the user chooses a circuit
  const [assignError, setAssignError] = useState<string | null>(null)

  const { run: fetchLaps } = laps
  const { run: fetchTracks } = tracks
  const { run: fetchCatalog } = catalog
  const refresh = useCallback(() => {
    void fetchLaps()
    void fetchTracks()
  }, [fetchLaps, fetchTracks])
  const recording = useRecording(refresh)

  useEffect(() => {
    refresh()
    void fetchCatalog()
  }, [refresh, fetchCatalog])

  // A different live circuit means a new profile may exist: refresh the circuit list.
  const liveTrackId = recording.status?.running ? recording.status.active_track_id : null
  useEffect(() => {
    if (liveTrackId !== null) void fetchTracks()
  }, [liveTrackId, fetchTracks])

  const tracksData = tracks.state.status === 'ready' ? tracks.state.data : null
  const choosable = useMemo(
    () => (tracksData ? { ...tracksData, active_track_id: liveTrackId } : null),
    [tracksData, liveTrackId],
  )
  // The circuit being browsed: the user's pick while it still exists, otherwise the live circuit
  // (or the best candidate). It never changes the live circuit, which comes from the game.
  const viewing: Viewing | null =
    !choosable ? null
    : pickedViewing !== null && isViewable(choosable, pickedViewing) ? pickedViewing
    : chooseViewing(choosable)

  const { reset: resetCompare } = compare
  const { reset: resetEvents } = events
  const { reset: resetDetail } = detail
  useEffect(() => {
    resetCompare()
    resetEvents()
    resetDetail()
  }, [viewing, resetCompare, resetEvents, resetDetail])

  const lapList = laps.state.status === 'ready' ? laps.state.data.laps : NO_LAPS
  const visibleLaps = useMemo(() => lapsFor(lapList, viewing), [lapList, viewing])
  const byId = useMemo(() => new Map(visibleLaps.map((l) => [l.id, l])), [visibleLaps])
  // The lap selection: the user's choice while its laps are on screen, otherwise the fastest valid lap
  // as reference and the next lap as comparison.
  const { refId, cmpId } = useMemo(() => {
    const valid = sel !== null && [sel.ref, sel.cmp].every((id) => id === null || byId.has(id))
    return valid && (sel.ref !== null || sel.cmp !== null)
      ? { refId: sel.ref, cmpId: sel.cmp }
      : (() => {
          const d = defaultSelection(visibleLaps)
          return { refId: d.ref, cmpId: d.cmp }
        })()
  }, [sel, byId, visibleLaps])
  const refLap = refId ? byId.get(refId) : undefined
  const cmpLap = cmpId ? byId.get(cmpId) : undefined

  const viewTrack = (next: Viewing) => setPickedViewing(next)

  // Lap distance of each chart sample, so the map can follow the chart cursor.
  const chartDistances = useMemo(() => {
    const raw = detail.state.status === 'ready' ? detail.state.data.data.distance_m : null
    return Array.isArray(raw) && raw.every((v) => typeof v === 'number') ? (raw as number[]) : null
  }, [detail.state])

  const assignLap = async (lapId: string, trackId: number) => {
    setAssignError(null)
    try {
      await assignLapTrack(lapId, trackId)
      refresh()
    } catch (e) {
      setAssignError(errorMessage(e))
    }
  }
  const catalogTracks = catalog.state.status === 'ready' ? catalog.state.data.tracks : null

  const selectRef = (id: string) => setSel({ ref: id, cmp: id === cmpId ? null : cmpId })
  const selectCmp = (id: string) => setSel({ ref: id === refId ? null : refId, cmp: id })

  const invalidSelected = !!(refLap && !refLap.valid) || !!(cmpLap && !cmpLap.valid)
  const needsAllow = invalidSelected && !allowInvalid
  const busy = compare.state.status === 'loading'
  const canCompare = !!refLap && !!cmpLap && !needsAllow && !busy

  const onCompare = async () => {
    if (!refLap || !cmpLap) return
    events.reset()
    detail.reset()
    const result = await compare.run(refLap.id, cmpLap.id, allowInvalid)
    if (result) await Promise.all([detail.run(result.id), events.run(result.id)])
  }

  let hint: string | null = null
  if (!refLap || !cmpLap) hint = 'Choose a reference and a comparison lap.'
  else if (needsAllow) hint = 'An invalid lap is selected: tick "Allow invalid laps" to compare it.'

  return (
    <>
      <header className="topbar">
        <h1 className="topbar__title">F1 Telemetry Coach</h1>
        <span className="topbar__page">Lap comparison</span>
        <span className="grow" />
        <RecordingControl {...recording} onStart={() => void recording.start()} onStop={() => void recording.stop()} />
      </header>
      <TrackBar
        tracks={tracksData}
        loading={tracks.state.status === 'loading'}
        error={tracks.state.status === 'error' ? tracks.state.error : null}
        viewing={viewing}
        onView={viewTrack}
        recording={recording.status}
      />
      <main className="page">
        <div className="workspace">
          <Panel
            title="Recorded laps"
            flush
            actions={<Button size="sm" onClick={() => void fetchLaps()} disabled={laps.state.status === 'loading'}>Reload</Button>}
          >
            {laps.state.status === 'loading' && <Placeholder>Loading laps from {API_BASE}...</Placeholder>}
            {laps.state.status === 'error' && (
              <div className="panel__body"><Notice tone="error" title="Could not load laps">{laps.state.error}</Notice></div>
            )}
            {laps.state.status === 'ready' && lapList.length === 0 && (
              <Placeholder>
                No recorded laps found in data/laps. Record some with: python udp_listener.py --record
              </Placeholder>
            )}
            {laps.state.status === 'ready' && lapList.length > 0 && visibleLaps.length === 0 && (
              <Placeholder>No recorded laps for this circuit yet.</Placeholder>
            )}
            {assignError && (
              <div className="panel__body"><Notice tone="error" title="Could not assign the circuit">{assignError}</Notice></div>
            )}
            {visibleLaps.length > 0 && (
              <LapTable laps={visibleLaps} refId={refId} cmpId={cmpId} onSelectRef={selectRef} onSelectCmp={selectCmp}
                assign={viewing === UNASSIGNED && catalogTracks ? { catalog: catalogTracks, onAssign: assignLap } : undefined} />
            )}
            {laps.state.status === 'ready' && laps.state.data.skipped.length > 0 && (
              <div className="panel__body">
                <Notice tone="warn" title={`${laps.state.data.skipped.length} lap file(s) could not be read`}>
                  <ul>{laps.state.data.skipped.map((s) => <li key={s.id}>{s.id}: {s.error}</li>)}</ul>
                </Notice>
              </div>
            )}
          </Panel>

          {visibleLaps.length > 0 && (
            <Panel title="Comparison" flush>
              <SelectedLap role="ref" lap={refLap} />
              <SelectedLap role="cmp" lap={cmpLap} />
              <div className="actions">
                <Checkbox label="Allow invalid laps" checked={allowInvalid}
                  onChange={(e) => setAllowInvalid(e.target.checked)} />
                <span className="actions__hint text-muted">{hint}</span>
                <Button variant="primary" disabled={!canCompare} onClick={() => void onCompare()}>
                  {busy ? 'Comparing...' : 'Compare'}
                </Button>
              </div>
              {compare.state.status === 'error' && (
                <div className="panel__body"><Notice tone="error" title="Comparison failed">{compare.state.error}</Notice></div>
              )}
              {compare.state.status === 'loading' && <Placeholder>Comparing laps...</Placeholder>}
              {compare.state.status === 'ready' && <Summary result={compare.state.data} />}
            </Panel>
          )}
        </div>

        {typeof viewing === 'number' && visibleLaps.length > 0 && (
          <div className={compare.state.status === 'ready' ? 'analysis analysis--split' : 'analysis'}>
            {compare.state.status === 'ready' && <TelemetryPanel state={detail.state} store={cursorStore} />}
            <MapPanel
              trackId={viewing}
              refLapId={refId}
              cmpLapId={cmpId}
              store={cursorStore}
              distances={chartDistances}
              version={visibleLaps.filter((l) => l.has_positions).length}
              recording={recording.status}
            />
          </div>
        )}

        {compare.state.status === 'ready' && (
          <Panel
            title={events.state.status === 'ready' ? `Detected events (${events.state.data.count})` : 'Detected events'}
            flush
          >
            {events.state.status === 'loading' && <Placeholder>Analysing events...</Placeholder>}
            {events.state.status === 'error' && (
              <div className="panel__body"><Notice tone="error" title="Event analysis failed">{events.state.error}</Notice></div>
            )}
            {events.state.status === 'ready' && events.state.data.count === 0 && (
              <Placeholder>No braking or corner events detected in this comparison.</Placeholder>
            )}
            {events.state.status === 'ready' && events.state.data.count > 0 && (
              <>
                <EventsTable events={events.state.data.events} />
                <p className="legend">
                  Differences are comparison minus reference. Time: green = comparison gained, red = comparison lost.
                  Braking, throttle and full throttle in metres: negative = earlier, positive = later.
                  Min speed in km/h: positive = faster. ? = ambiguous match, so no braking or throttle comparison.
                  Dash = nothing to compare.
                </p>
              </>
            )}
          </Panel>
        )}
      </main>
    </>
  )
}
