import { useEffect, useMemo, useRef, useState } from 'react'
import type { LapPathResponse, TrackMapResponse, WorldPath } from '../api/types'
import { useCursorIndex, type CursorStore } from '../charts/cursorStore'
import { Button } from '../design'
import {
  boundsOf, fitView, nearestOnPath, panBy, planeToScreen, pointAtDistance, polylinePoints, screenToPlane,
  toPlane, zoomAt, type PathXZ, type Size, type View,
} from '../lib/mapGeometry'
import { pickOrientation } from '../lib/mapOrientation'
import './map.css'

export interface TrackMapProps {
  /** The circuit trace (the driver's path); null when none has been built. */
  geometry: TrackMapResponse | null
  /** The selected reference / comparison laps' own recorded racing lines. */
  refPath: LapPathResponse | null
  cmpPath: LapPathResponse | null
  /** Shared with the telemetry charts: their cursor shows here, and a click here moves theirs. */
  store: CursorStore
  /** Lap distance of each chart sample, to turn the chart cursor index into a distance. */
  distances: number[] | null
  height?: number
}

const PICK_RADIUS_PX = 28
const DRAG_THRESHOLD_PX = 4
const ZOOM_STEP = 1.5

const asPath = (p: WorldPath | null | undefined): PathXZ | null => (p ? { distance_m: p.distance_m, x: p.x, z: p.z } : null)
const lapPath = (p: LapPathResponse | null): PathXZ | null => (p && p.available ? asPath(p) : null)

/** Interactive 2D track map: SVG, X/Z plane at one uniform scale, wheel zoom, drag to pan. */
export function TrackMap({ geometry, refPath, cmpPath, store, distances, height = 360 }: TrackMapProps) {
  const host = useRef<HTMLDivElement>(null)
  const svg = useRef<SVGSVGElement>(null)
  const drag = useRef<{ x: number; y: number; moved: boolean } | null>(null)
  const [size, setSize] = useState<Size>({ width: 0, height })
  const [user, setUser] = useState<View | null>(null) // set by zoom/pan; null = fit to the data
  const [show, setShow] = useState({ path: true, ref: true, cmp: true })
  const [hover, setHover] = useState<number | null>(null) // lap distance under the pointer
  const [picked, setPicked] = useState<number | null>(null) // lap distance last clicked

  const driver = useMemo(() => (geometry?.available ? asPath(geometry.driver_path) : null), [geometry])
  const ref = useMemo(() => lapPath(refPath), [refPath])
  const cmp = useMemo(() => lapPath(cmpPath), [cmpPath])
  const orientation = pickOrientation(
    driver ? geometry?.orientation : null,
    refPath?.available ? refPath.orientation : null,
    cmpPath?.available ? cmpPath.orientation : null,
  )
  const mirror = orientation.mirrorZ

  useEffect(() => {
    const el = host.current
    if (!el) return
    const measure = () => setSize({ width: el.clientWidth, height })
    const observer = new ResizeObserver(measure)
    observer.observe(el)
    measure()
    return () => observer.disconnect()
  }, [height])

  const layers = [driver, ref, cmp].filter((p): p is PathXZ => p !== null)
  const fitFor = (paths: PathXZ[]): View | null => {
    const bounds = boundsOf(paths, mirror)
    return bounds && size.width > 0 ? fitView(bounds, size) : null
  }
  const fit = fitFor(layers)
  const view = user ?? fit

  // Wheel zoom needs a non-passive listener to stop the page from scrolling at the same time.
  useEffect(() => {
    const el = svg.current
    if (!el) return
    const onWheel = (e: WheelEvent) => {
      const base = fitFor([driver, ref, cmp].filter((p): p is PathXZ => p !== null))
      if (!base) return
      e.preventDefault()
      const rect = el.getBoundingClientRect()
      setUser((cur) => zoomAt(cur ?? base, e.clientX - rect.left, e.clientY - rect.top, e.deltaY < 0 ? ZOOM_STEP : 1 / ZOOM_STEP, size, base))
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [driver, ref, cmp, mirror, size])

  const cursorIndex = useCursorIndex(store)
  const cursorDistance = cursorIndex !== null && distances ? (distances[cursorIndex] ?? null) : null

  const pickable: Array<[PathXZ, boolean]> = [
    ...(ref && show.ref ? ([[ref, mirror]] as Array<[PathXZ, boolean]>) : []),
    ...(cmp && show.cmp ? ([[cmp, mirror]] as Array<[PathXZ, boolean]>) : []),
    ...(driver && show.path ? ([[driver, mirror]] as Array<[PathXZ, boolean]>) : []),
  ]

  /** Lap distance of the closest drawn point to a pointer position (within a few pixels), if any. */
  const pick = (clientX: number, clientY: number): number | null => {
    const el = svg.current
    if (!el || !view) return null
    const rect = el.getBoundingClientRect()
    const [u, v] = screenToPlane(clientX - rect.left, clientY - rect.top, view, size)
    let best: { distance: number; gap: number } | null = null
    for (const [path, m] of pickable) {
      const hit = nearestOnPath(path, u, v, m)
      if (hit && (best === null || hit.gap < best.gap)) best = hit
      if (best && best.gap * view.scale <= PICK_RADIUS_PX) break // earlier layers win ties
    }
    return best && best.gap * view.scale <= PICK_RADIUS_PX ? best.distance : null
  }

  const onPointerDown = (e: React.PointerEvent) => {
    drag.current = { x: e.clientX, y: e.clientY, moved: false }
    ;(e.currentTarget as Element).setPointerCapture?.(e.pointerId)
  }
  const onPointerMove = (e: React.PointerEvent) => {
    const d = drag.current
    if (d && view) {
      const dx = e.clientX - d.x
      const dy = e.clientY - d.y
      if (d.moved || Math.hypot(dx, dy) > DRAG_THRESHOLD_PX) {
        d.moved = true
        d.x = e.clientX
        d.y = e.clientY
        setUser((cur) => panBy(cur ?? view, dx, dy))
      }
      return
    }
    setHover(pick(e.clientX, e.clientY))
  }
  const onPointerUp = (e: React.PointerEvent) => {
    const d = drag.current
    drag.current = null
    if (d && !d.moved) {
      const distance = pick(e.clientX, e.clientY)
      if (distance !== null) {
        setPicked(distance)
        store.focus(distance)
      }
    }
  }

  const zoomBy = (factor: number) => {
    if (view && fit) setUser(zoomAt(view, size.width / 2, size.height / 2, factor, size, fit))
  }
  const resetView = () => {
    setUser(null)
    setPicked(null)
  }

  const marker = (path: PathXZ | null, d: number | null) => (path && d !== null ? pointAtDistance(path, d) : null)
  const cursorRef = marker(ref ?? driver, cursorDistance)
  const cursorCmp = marker(cmp ?? driver, cursorDistance)
  const pickedPoint = marker(ref ?? cmp ?? driver, picked)
  const startPoint = marker(ref ?? cmp ?? driver, (ref ?? cmp ?? driver)?.distance_m[0] ?? null)

  const screen = (p: { x: number; z: number } | null): [number, number] | null => {
    if (!p || !view) return null
    const [u, v] = toPlane(p.x, p.z, mirror)
    return planeToScreen(u, v, view, size)
  }
  const line = (path: PathXZ | null, on: boolean) =>
    path && on && view ? polylinePoints(path, view, size, mirror) : null

  const q = geometry?.available ? geometry.quality : undefined
  const refPoint = screen(cursorRef)
  const cmpPoint = screen(cursorCmp)
  const pickedScreen = screen(pickedPoint)
  const startScreen = screen(startPoint)
  const hoverText = hover ?? picked

  return (
    <div className="trackmap">
      <div className="trackmap__toolbar">
        <span className="trackmap__layers">
          {driver && <Button size="sm" variant="toggle" pressed={show.path} onClick={() => setShow((s) => ({ ...s, path: !s.path }))}>Path</Button>}
          {ref && <Button size="sm" variant="toggle" pressed={show.ref} onClick={() => setShow((s) => ({ ...s, ref: !s.ref }))}>Ref</Button>}
          {cmp && <Button size="sm" variant="toggle" pressed={show.cmp} onClick={() => setShow((s) => ({ ...s, cmp: !s.cmp }))}>Cmp</Button>}
        </span>
        <span className="grow" />
        <span className="trackmap__readout mono">{hoverText !== null ? `${Math.round(hoverText)} m` : '—'}</span>
        <Button size="sm" aria-label="Zoom in" onClick={() => zoomBy(ZOOM_STEP)}>+</Button>
        <Button size="sm" aria-label="Zoom out" onClick={() => zoomBy(1 / ZOOM_STEP)}>&minus;</Button>
        <Button size="sm" onClick={resetView}>Reset</Button>
      </div>
      <div ref={host} className="trackmap__plot" style={{ height }}>
        <svg
          ref={svg}
          width={size.width}
          height={size.height}
          role="img"
          aria-label="Track map, X/Z plane"
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onPointerLeave={() => setHover(null)}
          onDoubleClick={resetView}
        >
          {view && (
            <>
              {line(driver, show.path) && <polyline className="trackmap__line trackmap__line--path" points={line(driver, show.path)!} />}
              {line(ref, show.ref) && <polyline className="trackmap__line trackmap__line--ref" points={line(ref, show.ref)!} />}
              {line(cmp, show.cmp) && <polyline className="trackmap__line trackmap__line--cmp" points={line(cmp, show.cmp)!} />}
              {startScreen && (
                <g className="trackmap__start" transform={`translate(${startScreen[0]},${startScreen[1]})`}>
                  <rect x={-3} y={-3} width={6} height={6} />
                  <text x={7} y={-5}>S/F</text>
                </g>
              )}
              {pickedScreen && <circle className="trackmap__picked" cx={pickedScreen[0]} cy={pickedScreen[1]} r={7} />}
              {refPoint && <circle className="trackmap__dot trackmap__dot--ref" cx={refPoint[0]} cy={refPoint[1]} r={4} />}
              {cmpPoint && <circle className="trackmap__dot trackmap__dot--cmp" cx={cmpPoint[0]} cy={cmpPoint[1]} r={4} />}
            </>
          )}
        </svg>
      </div>
      <div className="trackmap__meta mono">
        {driver && q
          ? `Driver path · ${q.lap_count} valid ${q.lap_count === 1 ? 'lap' : 'laps'} · spread ${q.spread_m} m · ` +
            `${q.closed ? 'closed' : 'not closed'} (${q.closure_gap_m} m gap)${q.cross_checked ? '' : ' · single lap, not cross-checked'}`
          : 'Selected laps only (no circuit trace yet)'}
        <span className={orientation.verified ? '' : 'text-warn'}>
          {orientation.verified
            ? ` · orientation verified by steering (r ${orientation.r?.toFixed(2)})`
            : ' · orientation not verified'}
        </span>
        {geometry?.axes && (
          <span className={geometry.axes.vertical_axis_verified ? '' : 'text-warn'}>
            {geometry.axes.vertical_axis_verified ? ` · vertical axis: ${geometry.axes.vertical_axis.toUpperCase()}` : ' · vertical axis not confirmed'}
          </span>
        )}
        <span className="text-dim"> {'·'} driver path, not the track centerline</span>
      </div>
    </div>
  )
}
