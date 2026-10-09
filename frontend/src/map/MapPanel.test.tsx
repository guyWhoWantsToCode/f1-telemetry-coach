// @vitest-environment jsdom
import { act, cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { getLapPath, getTrackMap } from '../api/client'
import type { LapPathResponse, TrackMapResponse } from '../api/types'
import { createCursorStore } from '../charts/cursorStore'
import { makeStatus } from '../recording/testStatus'
import { MapPanel, type MapPanelProps } from './MapPanel'

vi.mock('../api/client', () => ({
  getTrackMap: vi.fn(),
  getLapPath: vi.fn(),
  errorMessage: (e: unknown) => (e instanceof Error ? e.message : String(e)),
}))

const trackMap = vi.mocked(getTrackMap)
const lapPath = vi.mocked(getLapPath)

class FakeResizeObserver {
  observe() {}
  disconnect() {}
}

beforeEach(() => {
  vi.resetAllMocks()
  vi.stubGlobal('ResizeObserver', FakeResizeObserver)
  Object.defineProperty(HTMLElement.prototype, 'clientWidth', { configurable: true, get: () => 400 })
})
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

const orientation = { mirror_z: false, r: 0.7, verified: true, laps_checked: 2 }
const axes = { spans_m: { x: 400, y: 5, z: 200 }, vertical_axis: 'y' as const, vertical_axis_verified: true }
const world = { distance_m: [0, 100, 200], x: [0, 100, 200], y: [0, 0, 0], z: [0, 50, 0] }

const availableMap: TrackMapResponse = {
  track_id: 15, available: true, reason: null, message: null, kind: 'driver_path', driver_path: world,
  centerline: { available: false }, laps: ['a'], rejected: [], axes, orientation,
  quality: { lap_count: 1, cross_checked: false, spread_m: 0, max_spread_m: 0, closure_gap_m: 4, closed: true, path_length_m: 210, length_ratio: 1 },
}
const noPositions: TrackMapResponse = {
  track_id: 15, available: false, reason: 'no_positions', message: 'No position data has been recorded for this circuit yet.',
  driver_path: null, centerline: { available: false }, laps: [], rejected: [],
}
const lap = (id: string): LapPathResponse => ({ lap_id: id, track_id: 15, available: true, point_count: 3, axes, orientation, ...world })
const noLapPath = (id: string): LapPathResponse => ({ lap_id: id, track_id: 15, available: false, reason: 'no_positions', message: 'none' })

async function flush() {
  await act(async () => {
    await new Promise((r) => setTimeout(r, 0))
  })
}

function setup(over: Partial<MapPanelProps> = {}) {
  return render(
    <MapPanel trackId={15} refLapId="ref" cmpLapId="cmp" store={createCursorStore()} distances={null} version={1}
      recording={null} {...over} />,
  )
}

describe('MapPanel', () => {
  it('loads the circuit trace and both selected laps for the viewed circuit only', async () => {
    trackMap.mockResolvedValue(availableMap)
    lapPath.mockImplementation(async (id) => lap(id))
    const { container } = setup()
    await flush()
    expect(trackMap).toHaveBeenCalledWith(15, expect.anything())
    expect(lapPath.mock.calls.map((c) => c[0]).sort()).toEqual(['cmp', 'ref'])
    expect(container.querySelector('svg')).toBeTruthy()
    expect(container.querySelector('.trackmap__line--path')).toBeTruthy()
  })

  it('shows a useful empty state, never an invented circuit, when no positions were recorded', async () => {
    trackMap.mockResolvedValue(noPositions)
    lapPath.mockImplementation(async (id) => noLapPath(id))
    const { container } = setup()
    await flush()
    expect(container.querySelector('svg')).toBeNull()
    expect(container.querySelector('polyline')).toBeNull()
    expect(screen.getByText(/No position data for this circuit yet/)).toBeTruthy()
    expect(screen.getByText(/Motion packets/)).toBeTruthy()
  })

  it('explains why recorded positions could not be used', async () => {
    trackMap.mockResolvedValue({ ...noPositions, reason: 'no_usable_laps', message: 'Position data exists, but no lap was complete.',
      rejected: [{ lap_id: 'lapX', reason: 'incomplete lap (900 m of 5513 m)' }] })
    lapPath.mockImplementation(async (id) => noLapPath(id))
    setup()
    await flush()
    expect(screen.getByText(/no lap was complete/)).toBeTruthy()
    expect(screen.getByText(/lapX: incomplete lap/)).toBeTruthy()
  })

  it('still draws a selected lap when the circuit has no trace yet', async () => {
    trackMap.mockResolvedValue(noPositions)
    lapPath.mockImplementation(async (id) => (id === 'ref' ? lap(id) : noLapPath(id)))
    const { container } = setup()
    await flush()
    expect(container.querySelector('.trackmap__line--ref')).toBeTruthy()
    expect(container.querySelector('.trackmap__line--path')).toBeNull()
    expect(container.querySelector('.trackmap__line--cmp')).toBeNull()
  })

  it('shows a loading state, then an error if nothing could be loaded', async () => {
    let fail: (e: Error) => void = () => {}
    trackMap.mockReturnValue(new Promise((_, reject) => { fail = reject }))
    lapPath.mockImplementation(async (id) => noLapPath(id))
    setup()
    expect(screen.getByText('Loading track map...')).toBeTruthy()
    await act(async () => {
      fail(new Error('Cannot reach the API'))
      await new Promise((r) => setTimeout(r, 0))
    })
    expect(screen.getByText('Could not load the track map')).toBeTruthy()
    expect(screen.getByText('Cannot reach the API')).toBeTruthy()
  })

  it('does not request lap paths when no laps are selected', async () => {
    trackMap.mockResolvedValue(availableMap)
    setup({ refLapId: null, cmpLapId: null })
    await flush()
    expect(lapPath).not.toHaveBeenCalled()
  })

  it('reloads for another circuit and when new laps arrive, without mixing data', async () => {
    trackMap.mockResolvedValue(availableMap)
    lapPath.mockImplementation(async (id) => lap(id))
    const { rerender } = setup()
    await flush()
    trackMap.mockResolvedValue({ ...noPositions, track_id: 11 })
    lapPath.mockImplementation(async (id) => noLapPath(id))
    rerender(<MapPanel trackId={11} refLapId="r2" cmpLapId={null} store={createCursorStore()} distances={null} version={1} recording={null} />)
    await flush()
    expect(trackMap).toHaveBeenLastCalledWith(11, expect.anything())
    expect(screen.getByText(/No position data for this circuit yet/)).toBeTruthy()
    const calls = trackMap.mock.calls.length
    rerender(<MapPanel trackId={11} refLapId="r2" cmpLapId={null} store={createCursorStore()} distances={null} version={2} recording={null} />)
    await flush()
    expect(trackMap.mock.calls.length).toBeGreaterThan(calls)
  })

  it('warns when recording is running but no Motion packets arrive', async () => {
    trackMap.mockResolvedValue(noPositions)
    lapPath.mockImplementation(async (id) => noLapPath(id))
    setup({ recording: makeStatus({ state: 'recording', running: true, receiving: true, packets_total: 400, motion_packets: 0 }) })
    await flush()
    expect(screen.getByText('No Motion packets are arriving')).toBeTruthy()
    cleanup()
    setup({ recording: makeStatus({ state: 'recording', running: true, receiving: true, packets_total: 400, motion_packets: 120 }) })
    await flush()
    expect(screen.queryByText('No Motion packets are arriving')).toBeNull()
  })
})
