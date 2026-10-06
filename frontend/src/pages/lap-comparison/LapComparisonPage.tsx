import { useEffect, useMemo, useState } from 'react'
import { API_BASE, compareLaps, getEvents, getLaps } from '../../api/client'
import type { LapMeta } from '../../api/types'
import { Badge, Button, Checkbox, Notice, Panel, Placeholder } from '../../design'
import { useAsyncAction } from '../../hooks/useAsyncAction'
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

/** Starting selection from the real laps: fastest valid lap as reference, next lap as comparison. */
function defaultSelection(laps: LapMeta[]): { ref: string | null; cmp: string | null } {
  const timed = laps.filter((l) => l.valid && l.lap_time_ms !== null)
  const best = timed.sort((a, b) => (a.lap_time_ms ?? 0) - (b.lap_time_ms ?? 0))[0] ?? laps[0]
  if (!best) return { ref: null, cmp: null }
  const others = laps.filter((l) => l.id !== best.id)
  const next = others.find((l) => l.valid) ?? others[0]
  return { ref: best.id, cmp: next?.id ?? null }
}

function SelectedLap({ label, lap }: { label: string; lap: LapMeta | undefined }) {
  return (
    <span className="selection__slot">
      <span className="selection__label">{label}</span>
      {lap ? (
        <>
          <span className="mono">Lap {lap.lap_number} {lap.lap_time ?? ''}</span>
          {lap.valid ? <Badge>Valid</Badge> : <Badge tone="warn">Invalid</Badge>}
        </>
      ) : (
        <span className="text-dim">not selected</span>
      )}
    </span>
  )
}

export default function LapComparisonPage() {
  const laps = useAsyncAction(loadLaps)
  const compare = useAsyncAction(runCompare)
  const events = useAsyncAction(loadEvents)
  const [refId, setRefId] = useState<string | null>(null)
  const [cmpId, setCmpId] = useState<string | null>(null)
  const [allowInvalid, setAllowInvalid] = useState(false)

  const { run: fetchLaps } = laps
  useEffect(() => {
    void fetchLaps().then((res) => {
      if (!res) return
      const start = defaultSelection(res.laps)
      setRefId((cur) => cur ?? start.ref)
      setCmpId((cur) => cur ?? start.cmp)
    })
  }, [fetchLaps])

  const lapList = laps.state.status === 'ready' ? laps.state.data.laps : NO_LAPS
  const byId = useMemo(() => new Map(lapList.map((l) => [l.id, l])), [lapList])
  const refLap = refId ? byId.get(refId) : undefined
  const cmpLap = cmpId ? byId.get(cmpId) : undefined

  const selectRef = (id: string) => {
    setRefId(id)
    if (id === cmpId) setCmpId(null)
  }
  const selectCmp = (id: string) => {
    setCmpId(id)
    if (id === refId) setRefId(null)
  }

  const invalidSelected = !!(refLap && !refLap.valid) || !!(cmpLap && !cmpLap.valid)
  const needsAllow = invalidSelected && !allowInvalid
  const busy = compare.state.status === 'loading'
  const canCompare = !!refLap && !!cmpLap && !needsAllow && !busy

  const onCompare = async () => {
    if (!refLap || !cmpLap) return
    events.reset()
    const result = await compare.run(refLap.id, cmpLap.id, allowInvalid)
    if (result) await events.run(result.id)
  }

  let hint: string | null = null
  if (!refLap || !cmpLap) hint = 'Choose a reference and a comparison lap.'
  else if (needsAllow) hint = 'An invalid lap is selected: tick "Allow invalid laps" to compare it.'

  return (
    <>
      <header className="topbar">
        <h1 className="topbar__title">F1 Telemetry Coach</h1>
        <span className="topbar__page">Lap comparison</span>
      </header>
      <main className="page">
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
          {lapList.length > 0 && (
            <LapTable laps={lapList} refId={refId} cmpId={cmpId} onSelectRef={selectRef} onSelectCmp={selectCmp} />
          )}
          {laps.state.status === 'ready' && laps.state.data.skipped.length > 0 && (
            <div className="panel__body">
              <Notice tone="warn" title={`${laps.state.data.skipped.length} lap file(s) could not be read`}>
                <ul>{laps.state.data.skipped.map((s) => <li key={s.id}>{s.id}: {s.error}</li>)}</ul>
              </Notice>
            </div>
          )}
        </Panel>

        {lapList.length > 0 && (
          <Panel title="Comparison">
            <div className="selection">
              <SelectedLap label="Reference" lap={refLap} />
              <SelectedLap label="Comparison" lap={cmpLap} />
              <span className="grow" />
              {hint && <span className="text-muted">{hint}</span>}
              <Checkbox label="Allow invalid laps" checked={allowInvalid}
                onChange={(e) => setAllowInvalid(e.target.checked)} />
              <Button variant="primary" disabled={!canCompare} onClick={() => void onCompare()}>
                {busy ? 'Comparing...' : 'Compare'}
              </Button>
            </div>
          </Panel>
        )}

        {compare.state.status === 'error' && (
          <Notice tone="error" title="Comparison failed">{compare.state.error}</Notice>
        )}
        {compare.state.status === 'loading' && <Placeholder>Comparing laps...</Placeholder>}
        {compare.state.status === 'ready' && <Summary result={compare.state.data} />}

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
