// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { LapPathResponse, MapOrientation, TrackMapResponse } from '../api/types'
import { createCursorStore } from '../charts/cursorStore'
import { fitView, boundsOf, planeToScreen, toPlane } from '../lib/mapGeometry'
import { TrackMap } from './TrackMap'

// jsdom has no layout: give the map a size and a resize observer we can drive.
let width = 400
const observers: Array<() => void> = []
class FakeResizeObserver {
  constructor(cb: () => void) {
    observers.push(cb)
  }
  observe() {}
  disconnect() {}
}

beforeEach(() => {
  width = 400
  observers.length = 0
  vi.stubGlobal('ResizeObserver', FakeResizeObserver)
  Object.defineProperty(HTMLElement.prototype, 'clientWidth', { configurable: true, get: () => width })
  Element.prototype.getBoundingClientRect = () =>
    ({ left: 0, top: 0, width, height: 360, right: width, bottom: 360, x: 0, y: 0, toJSON: () => ({}) }) as DOMRect
})
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

// A 400 m x 200 m rectangle driven clockwise (X right, Z down); lap distance every 100 m.
const rectX = [0, 100, 200, 300, 400, 400, 300, 200, 100, 0]
const rectZ = [0, 0, 0, 0, 0, 200, 200, 200, 200, 200]
const rectD = [0, 100, 200, 300, 400, 600, 700, 800, 900, 1000]
const orientation: MapOrientation = { mirror_z: false, r: 0.8, verified: true, laps_checked: 3 }
const axes = { spans_m: { x: 400, y: 5, z: 200 }, vertical_axis: 'y' as const, vertical_axis_verified: true }

const geometry = (over: Partial<TrackMapResponse> = {}): TrackMapResponse => ({
  track_id: 15, available: true, reason: null, message: null, kind: 'driver_path',
  driver_path: { distance_m: rectD, x: rectX, y: rectX.map(() => 0), z: rectZ },
  centerline: { available: false, reason: 'not derivable' }, laps: ['a', 'b'], rejected: [],
  quality: { lap_count: 2, cross_checked: true, spread_m: 1.5, max_spread_m: 3, closure_gap_m: 5, closed: true, path_length_m: 1000, length_ratio: 1 },
  axes, orientation, ...over,
})

const lap = (id: string, dz = 0, orient = orientation): LapPathResponse => ({
  lap_id: id, track_id: 15, available: true, point_count: 10, axes, orientation: orient,
  distance_m: rectD, x: rectX, y: rectX.map(() => 0), z: rectZ.map((z) => z + dz),
})

const lines = (container: HTMLElement) => ({
  path: container.querySelector('.trackmap__line--path'),
  ref: container.querySelector('.trackmap__line--ref'),
  cmp: container.querySelector('.trackmap__line--cmp'),
})

function setup(props: Partial<Parameters<typeof TrackMap>[0]> = {}) {
  const store = createCursorStore()
  const utils = render(
    <TrackMap geometry={geometry()} refPath={lap('ref')} cmpPath={lap('cmp', 10)} store={store} distances={rectD} {...props} />,
  )
  return { store, ...utils }
}

const press = (el: Element, type: string, x: number, y: number) =>
  act(() => {
    el.dispatchEvent(new MouseEvent(type, { clientX: x, clientY: y, bubbles: true }))
  })

describe('TrackMap', () => {
  it('draws the circuit trace and both laps as separate layers', () => {
    const { container } = setup()
    const l = lines(container)
    expect(l.path).toBeTruthy()
    expect(l.ref).toBeTruthy()
    expect(l.cmp).toBeTruthy()
    expect(l.path!.getAttribute('points')!.split(' ')).toHaveLength(10)
  })

  it('layers can be hidden and shown again', () => {
    const { container } = setup()
    fireEvent.click(screen.getByRole('button', { name: 'Cmp' }))
    expect(lines(container).cmp).toBeNull()
    expect(lines(container).ref).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Path' }))
    expect(lines(container).path).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Cmp' }))
    expect(lines(container).cmp).toBeTruthy()
  })

  it('preserves the circuit proportions on screen', () => {
    const { container } = setup({ cmpPath: null })
    const pts = lines(container).ref!.getAttribute('points')!.split(' ').map((p) => p.split(',').map(Number))
    const xs = pts.map((p) => p[0])
    const ys = pts.map((p) => p[1])
    const w = Math.max(...xs) - Math.min(...xs)
    const h = Math.max(...ys) - Math.min(...ys)
    expect(w / h).toBeCloseTo(400 / 200, 1) // X and Z drawn at the same scale
  })

  it('flips Z only when the steering says the world is mirrored', () => {
    const points = (container: HTMLElement) =>
      lines(container).ref!.getAttribute('points')!.split(' ').map((p) => p.split(',').map(Number))
    const plain = points(setup().container)
    cleanup()
    const flip = { ...orientation, mirror_z: true }
    const mirrored = points(setup({
      geometry: geometry({ orientation: flip }), refPath: lap('ref', 0, flip), cmpPath: lap('cmp', 10, flip),
    }).container)
    expect(plain[0][1]).toBeLessThan(plain[5][1]) // Z down: the far side is lower on screen
    expect(mirrored[0][1]).toBeGreaterThan(mirrored[5][1]) // flipped
    expect(mirrored.map((p) => p[0])).toEqual(plain.map((p) => p[0])) // X is untouched
  })

  it('says whether the orientation and vertical axis were verified', () => {
    setup()
    expect(screen.getByText(/orientation verified by steering/)).toBeTruthy()
    expect(screen.getByText(/vertical axis: Y/)).toBeTruthy()
    expect(screen.getByText(/driver path, not the track centerline/)).toBeTruthy()
    cleanup()
    setup({ geometry: geometry({ orientation: { ...orientation, verified: false, r: null }, axes: { ...axes, vertical_axis_verified: false } }),
      refPath: lap('ref', 0, { ...orientation, verified: false, r: null }), cmpPath: null })
    expect(screen.getByText(/orientation not verified/)).toBeTruthy()
    expect(screen.getByText(/vertical axis not confirmed/)).toBeTruthy()
  })

  it('works with the selected laps alone when there is no circuit trace', () => {
    const { container } = setup({ geometry: null })
    expect(lines(container).path).toBeNull()
    expect(lines(container).ref).toBeTruthy()
    expect(screen.getByText(/Selected laps only/)).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Path' })).toBeNull()
  })

  it('shows the chart cursor as a position on each lap', () => {
    const { container, store } = setup()
    act(() => store.set(2)) // chart sample 2 = 200 m
    const ref = container.querySelector('.trackmap__dot--ref')!
    const cmp = container.querySelector('.trackmap__dot--cmp')!
    const fit = fitView(boundsOf([{ distance_m: rectD, x: rectX, z: rectZ }, { distance_m: rectD, x: rectX, z: rectZ.map((z) => z + 10) }], false)!, { width: 400, height: 360 })
    const [rx, ry] = planeToScreen(...toPlane(200, 0, false), fit, { width: 400, height: 360 })
    const [cx, cy] = planeToScreen(...toPlane(200, 10, false), fit, { width: 400, height: 360 })
    expect(Number(ref.getAttribute('cx'))).toBeCloseTo(rx, 0)
    expect(Number(ref.getAttribute('cy'))).toBeCloseTo(ry, 0)
    expect(Number(cmp.getAttribute('cx'))).toBeCloseTo(cx, 0)
    expect(Number(cmp.getAttribute('cy'))).toBeCloseTo(cy, 0)
    act(() => store.set(null))
    expect(container.querySelector('.trackmap__dot--ref')).toBeNull() // pointer left the charts
  })

  it('clicking a point on the map asks the charts to show that lap distance', () => {
    const { container, store } = setup({ cmpPath: null })
    const focus = vi.fn()
    store.onFocus(focus)
    const svg = container.querySelector('svg')!
    const pts = lines(container).ref!.getAttribute('points')!.split(' ').map((p) => p.split(',').map(Number))
    const [x, y] = pts[3] // the point at 300 m
    press(svg, 'pointerdown', x + 3, y + 2)
    press(svg, 'pointerup', x + 3, y + 2)
    expect(focus).toHaveBeenCalledTimes(1)
    expect(focus).toHaveBeenCalledWith(300)
  })

  it('a click far from any drawn point does nothing, and a drag pans instead of clicking', () => {
    const { container, store } = setup({ cmpPath: null })
    const focus = vi.fn()
    store.onFocus(focus)
    const svg = container.querySelector('svg')!
    press(svg, 'pointerdown', 5, 5)
    press(svg, 'pointerup', 5, 5)
    expect(focus).not.toHaveBeenCalled()
    const before = lines(container).ref!.getAttribute('points')
    press(svg, 'pointerdown', 100, 100)
    press(svg, 'pointermove', 140, 130)
    press(svg, 'pointerup', 140, 130)
    expect(focus).not.toHaveBeenCalled()
    expect(lines(container).ref!.getAttribute('points')).not.toBe(before)
  })

  it('zooms with the wheel and the buttons, and Reset restores the fitted view', () => {
    const { container } = setup({ cmpPath: null })
    const fitted = lines(container).ref!.getAttribute('points')
    fireEvent.wheel(container.querySelector('svg')!, { deltaY: -100, clientX: 200, clientY: 180 })
    const zoomed = lines(container).ref!.getAttribute('points')
    expect(zoomed).not.toBe(fitted)
    fireEvent.click(screen.getByRole('button', { name: 'Zoom out' }))
    fireEvent.click(screen.getByRole('button', { name: 'Zoom in' }))
    expect(lines(container).ref!.getAttribute('points')).not.toBe(fitted)
    fireEvent.click(screen.getByRole('button', { name: 'Reset' }))
    expect(lines(container).ref!.getAttribute('points')).toBe(fitted)
  })

  it('re-fits when the window is resized', () => {
    const { container } = setup({ cmpPath: null })
    const before = lines(container).ref!.getAttribute('points')
    width = 800
    act(() => observers.forEach((cb) => cb()))
    expect(container.querySelector('svg')!.getAttribute('width')).toBe('800')
    expect(lines(container).ref!.getAttribute('points')).not.toBe(before)
  })
})
