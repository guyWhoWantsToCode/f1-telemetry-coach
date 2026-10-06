import { useEffect, useRef } from 'react'
import uPlot from 'uplot'
import 'uplot/dist/uPlot.min.css'
import './chart.css'
import type { CursorStore } from './cursorStore'

export interface ChartSeries {
  label: string
  values: number[]
  /** CSS custom property holding the stroke color, e.g. "--chart-ref". */
  colorVar: string
  width?: number
}

export interface TelemetryChartProps {
  x: number[]
  series: ChartSeries[]
  height: number
  /** Charts sharing a key share their cursor and x zoom. */
  syncKey: string
  store: CursorStore
  ariaLabel: string
  /** Show distance tick labels and axis title (normally only the bottom chart). */
  showXAxis?: boolean
  yTicks?: number[]
  yRange?: (min: number, max: number) => [number, number]
  formatY?: (value: number) => string
  /** Delta chart: heavy zero line, red fill where above zero (time lost), green below (gained). */
  deltaFill?: boolean
}

const cssVar = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim()

/** A single uPlot chart. Straight line segments between samples (no smoothing), canvas rendered. */
export function TelemetryChart(props: TelemetryChartProps) {
  const { x, series, height, syncKey, store, showXAxis = false, yTicks, yRange, formatY, deltaFill } = props
  const host = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const el = host.current
    if (!el) return

    const font = `11px ${cssVar('--font-sans')}`
    const axisColor = cssVar('--chart-axis')
    const gridColor = cssVar('--chart-grid')
    const grid = { stroke: gridColor, width: 1 }
    const fmt = formatY ?? ((v: number) => String(Math.round(v * 100) / 100))

    const drawDelta = (u: uPlot) => {
      const { ctx, bbox } = u
      const xs = u.data[0]
      const ys = u.data[1] as number[]
      const zeroY = u.valToPos(0, 'y', true)
      const area = new Path2D()
      for (let i = 0; i < xs.length; i++) {
        const px = u.valToPos(xs[i], 'x', true)
        const py = u.valToPos(ys[i], 'y', true)
        if (i === 0) area.moveTo(px, py)
        else area.lineTo(px, py)
      }
      area.lineTo(u.valToPos(xs[xs.length - 1], 'x', true), zeroY)
      area.lineTo(u.valToPos(xs[0], 'x', true), zeroY)
      area.closePath()

      const fillRegion = (top: number, bottom: number, color: string) => {
        if (bottom <= top) return
        ctx.save()
        ctx.beginPath()
        ctx.rect(bbox.left, top, bbox.width, bottom - top)
        ctx.clip()
        ctx.globalAlpha = 0.28
        ctx.fillStyle = color
        ctx.fill(area)
        ctx.restore()
      }
      fillRegion(bbox.top, Math.min(zeroY, bbox.top + bbox.height), cssVar('--color-loss')) // above zero: time lost
      fillRegion(Math.max(zeroY, bbox.top), bbox.top + bbox.height, cssVar('--color-gain')) // below zero: time gained

      if (zeroY >= bbox.top && zeroY <= bbox.top + bbox.height) {
        ctx.save()
        ctx.strokeStyle = cssVar('--chart-zero')
        ctx.lineWidth = 1.5 * (window.devicePixelRatio || 1)
        ctx.beginPath()
        ctx.moveTo(bbox.left, zeroY)
        ctx.lineTo(bbox.left + bbox.width, zeroY)
        ctx.stroke()
        ctx.restore()
      }
    }

    const opts: uPlot.Options = {
      width: el.clientWidth || 600,
      height,
      padding: [8, 16, 0, 0],
      legend: { show: false },
      cursor: {
        y: false,
        sync: { key: syncKey, scales: ['x', null] }, // share cursor + x zoom, never y
        drag: { x: true, y: false, setScale: true },
        points: { size: 6, width: 1 },
      },
      scales: { x: { time: false }, y: { range: yRange ? (_u, min, max) => yRange(min, max) : undefined } },
      axes: [
        {
          stroke: axisColor,
          font,
          grid,
          ticks: showXAxis ? { stroke: gridColor, width: 1, size: 4 } : { show: false },
          size: showXAxis ? 40 : 8,
          label: showXAxis ? 'Lap distance (m)' : undefined,
          labelFont: font,
          labelSize: 16,
          values: (_u, splits) => splits.map((v) => (showXAxis ? String(Math.round(v)) : '')),
        },
        {
          stroke: axisColor,
          font,
          grid,
          ticks: { stroke: gridColor, width: 1, size: 4 },
          size: 56,
          splits: yTicks ? () => yTicks : undefined,
          values: (_u, splits) => splits.map(fmt),
        },
      ],
      series: [
        {},
        ...series.map((s): uPlot.Series => ({
          label: s.label,
          stroke: cssVar(s.colorVar),
          width: s.width ?? 1.25,
          points: { show: false },
          paths: uPlot.paths.linear!(),
        })),
      ],
      hooks: {
        setCursor: [(u) => store.set(u.cursor.idx ?? null)],
        draw: deltaFill ? [drawDelta] : [],
      },
    }

    const plot = new uPlot(opts, [x, ...series.map((s) => s.values)], el)
    const observer = new ResizeObserver(() => {
      const width = el.clientWidth
      if (width > 0 && width !== plot.width) plot.setSize({ width, height })
    })
    observer.observe(el)

    return () => {
      observer.disconnect()
      plot.destroy()
    }
  }, [x, series, height, syncKey, store, showXAxis, yTicks, yRange, formatY, deltaFill])

  return <div ref={host} className="chart__plot" role="img" aria-label={props.ariaLabel} />
}
