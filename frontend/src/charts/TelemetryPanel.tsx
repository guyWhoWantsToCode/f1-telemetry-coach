import { useMemo, type ReactNode } from 'react'
import type { ComparisonDetail, LapMeta } from '../api/types'
import { Notice, Panel, Placeholder } from '../design'
import type { AsyncState } from '../hooks/useAsyncAction'
import { ChartDataError, toChartData, type ChartData } from '../lib/chartData'
import { fmtSeconds } from '../lib/format'
import { createCursorStore, useCursorIndex, type CursorStore } from './cursorStore'
import { TelemetryChart, type ChartSeries } from './TelemetryChart'

const SYNC_KEY = 'comparison-telemetry'
const PERCENT_TICKS = [0, 50, 100]
const percentRange = (): [number, number] => [-4, 104]
const deltaRange = (min: number, max: number): [number, number] => {
  const lo = Math.min(min, 0)
  const hi = Math.max(max, 0)
  const pad = (hi - lo) * 0.08 || 0.1
  return [lo - pad, hi + pad]
}
const fmtDeltaTick = (v: number) => (v === 0 ? '0' : `${v > 0 ? '+' : '−'}${Math.abs(v).toFixed(1)}`)
const fmtPercentTick = (v: number) => `${Math.round(v)}%`
const fmtSpeedTick = (v: number) => String(Math.round(v))

const lapLabel = (lap: LapMeta | null, fallback: string) =>
  lap ? `Lap ${lap.lap_number}${lap.lap_time ? ` ${lap.lap_time}` : ''}` : fallback

function Key({ colorVar, children }: { colorVar: string; children: ReactNode }) {
  return (
    <span className="chart-strip__key">
      <span className="chart__swatch" style={{ background: `var(${colorVar})` }} />
      {children}
    </span>
  )
}

/** A value at the synchronized cursor, or a dash while the pointer is outside the charts. */
function LiveValue(props: { store: CursorStore; values: number[]; format: (v: number) => string; colorVar?: string; tone?: boolean }) {
  const idx = useCursorIndex(props.store)
  const value = idx === null ? null : props.values[idx]
  const toneClass = props.tone && value !== null && Math.abs(value) >= 0.0005 ? (value > 0 ? 'text-loss' : 'text-gain') : ''
  return (
    <span className="chart__value mono">
      {props.colorVar && <span className="chart__swatch" style={{ background: `var(${props.colorVar})` }} />}
      <span className={toneClass}>{value === null ? '—' : props.format(value)}</span>
    </span>
  )
}

function LiveDistance({ store, x }: { store: CursorStore; x: number[] }) {
  const idx = useCursorIndex(store)
  return <span className="chart-strip__distance mono">{idx === null ? '—' : `${Math.round(x[idx])} m`}</span>
}

function ChartBlock(props: {
  title: string
  note?: string
  values: ReactNode
  children: ReactNode
}) {
  return (
    <div className="chart">
      <div className="chart__header">
        <span className="chart__title">{props.title}{props.note && <small>{props.note}</small>}</span>
        <span className="chart__values">{props.values}</span>
      </div>
      {props.children}
    </div>
  )
}

const pair = (data: { ref: number[]; cmp: number[] }): ChartSeries[] => [
  { label: 'Reference', values: data.ref, colorVar: '--chart-ref' },
  { label: 'Comparison', values: data.cmp, colorVar: '--chart-cmp' },
]

function Charts({ detail, data }: { detail: ComparisonDetail; data: ChartData }) {
  const store = useMemo(() => createCursorStore(), [])
  const speed = useMemo(() => pair(data.speed), [data])
  const throttle = useMemo(() => pair(data.throttle), [data])
  const brake = useMemo(() => pair(data.brake), [data])
  const delta = useMemo<ChartSeries[]>(
    () => [{ label: 'Delta', values: data.delta, colorVar: '--chart-delta', width: 1.5 }],
    [data],
  )
  const common = { x: data.distance, syncKey: SYNC_KEY, store }

  return (
    <>
      <div className="chart-strip">
        <Key colorVar="--chart-ref">Reference {lapLabel(detail.reference, 'lap')}</Key>
        <Key colorVar="--chart-cmp">Comparison {lapLabel(detail.comparison, 'lap')}</Key>
        <span className="grow" />
        <span className="text-dim">Drag to zoom, double-click to reset</span>
        <LiveDistance store={store} x={data.distance} />
      </div>

      <ChartBlock
        title="Speed"
        note="km/h"
        values={<>
          <LiveValue store={store} values={data.speed.ref} format={fmtSpeedTick} colorVar="--chart-ref" />
          <LiveValue store={store} values={data.speed.cmp} format={fmtSpeedTick} colorVar="--chart-cmp" />
        </>}
      >
        <TelemetryChart {...common} series={speed} height={288} formatY={fmtSpeedTick} ariaLabel="Speed against lap distance" />
      </ChartBlock>

      <ChartBlock
        title="Time delta"
        note="s, positive = comparison slower"
        values={<LiveValue store={store} values={data.delta} format={(v) => fmtSeconds(v * 1000)} tone />}
      >
        <TelemetryChart {...common} series={delta} height={216} yRange={deltaRange} formatY={fmtDeltaTick} deltaFill
          ariaLabel="Time delta against lap distance" />
      </ChartBlock>

      <ChartBlock
        title="Throttle"
        note="%"
        values={<>
          <LiveValue store={store} values={data.throttle.ref} format={fmtPercentTick} colorVar="--chart-ref" />
          <LiveValue store={store} values={data.throttle.cmp} format={fmtPercentTick} colorVar="--chart-cmp" />
        </>}
      >
        <TelemetryChart {...common} series={throttle} height={128} yTicks={PERCENT_TICKS} yRange={percentRange}
          formatY={fmtPercentTick} ariaLabel="Throttle against lap distance" />
      </ChartBlock>

      <ChartBlock
        title="Brake"
        note="%"
        values={<>
          <LiveValue store={store} values={data.brake.ref} format={fmtPercentTick} colorVar="--chart-ref" />
          <LiveValue store={store} values={data.brake.cmp} format={fmtPercentTick} colorVar="--chart-cmp" />
        </>}
      >
        <TelemetryChart {...common} series={brake} height={168} yTicks={PERCENT_TICKS} yRange={percentRange}
          formatY={fmtPercentTick} showXAxis ariaLabel="Brake against lap distance" />
      </ChartBlock>
    </>
  )
}

/** The telemetry chart panel with its loading, error, empty and malformed-data states. */
export function TelemetryPanel({ state }: { state: AsyncState<ComparisonDetail> }) {
  const parsed = useMemo(() => {
    if (state.status !== 'ready') return null
    try {
      return { data: toChartData(state.data.data) }
    } catch (e) {
      if (e instanceof ChartDataError) return { problem: e }
      throw e
    }
  }, [state])

  let body: ReactNode = null
  if (state.status === 'idle' || state.status === 'loading') body = <Placeholder>Loading telemetry...</Placeholder>
  else if (state.status === 'error') body = <div className="panel__body"><Notice tone="error" title="Could not load telemetry">{state.error}</Notice></div>
  else if (parsed?.problem?.kind === 'empty') body = <Placeholder>This comparison has no telemetry points to chart.</Placeholder>
  else if (parsed?.problem) body = <div className="panel__body"><Notice tone="error" title="Telemetry data is malformed">{parsed.problem.message}</Notice></div>
  else if (parsed?.data && state.status === 'ready') body = <Charts detail={state.data} data={parsed.data} />

  return <Panel title="Telemetry by lap distance" flush surface="plot">{body}</Panel>
}
