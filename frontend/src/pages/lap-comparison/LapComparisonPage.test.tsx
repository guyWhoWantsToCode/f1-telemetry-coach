// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { assignLapTrack, getLapPath, getLaps, getRecordingStatus, getTrackCatalog, getTrackMap, getTracks } from '../../api/client'
import { CATALOG, makeLap, makeTracks } from '../../lib/testData'
import { makeStatus } from '../../recording/testStatus'
import LapComparisonPage from './LapComparisonPage'

vi.mock('../../api/client', () => ({
  API_BASE: 'http://api.test',
  errorMessage: (e: unknown) => (e instanceof Error ? e.message : String(e)),
  getLaps: vi.fn(),
  getTracks: vi.fn(),
  getTrackCatalog: vi.fn(),
  assignLapTrack: vi.fn(),
  getRecordingStatus: vi.fn(),
  startRecording: vi.fn(),
  stopRecording: vi.fn(),
  compareLaps: vi.fn(),
  getEvents: vi.fn(),
  getComparison: vi.fn(),
  getTrackMap: vi.fn(),
  getLapPath: vi.fn(),
}))

// The canvas charts need a real browser (matchMedia); these tests do not draw any.
vi.mock('../../charts/TelemetryPanel', () => ({ TelemetryPanel: () => null }))

const laps = vi.mocked(getLaps)
const tracks = vi.mocked(getTracks)
const catalog = vi.mocked(getTrackCatalog)
const assign = vi.mocked(assignLapTrack)
const status = vi.mocked(getRecordingStatus)
const trackMap = vi.mocked(getTrackMap)
const lapPath = vi.mocked(getLapPath)

const cotaLap = makeLap({ id: 'cota_lap01', lap_number: 1, track_id: 15 })
const monzaLap = makeLap({ id: 'monza_lap01', lap_number: 1, track_id: 11, track_name: 'Monza', lap_time: '1:20.000', lap_time_ms: 80000 })
const suzukaLap = makeLap({ id: 'suzuka_lap01', lap_number: 1, track_id: 13, track_name: 'Suzuka', lap_time: '1:30.000', lap_time_ms: 90000 })
const legacyLap = makeLap({ id: 'old_lap01', lap_number: 1, track_id: null, track_name: null, track_source: null })

const recordingOn = (trackId: number, name: string) =>
  makeStatus({ state: 'recording', running: true, receiving: true, packets_per_second: 600, active_track_id: trackId, active_track_name: name })

async function flush(ms = 0) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms)
  })
}

function viewedSelect() {
  return screen.getByLabelText('Circuit being viewed') as HTMLSelectElement
}

const lapsTable = () => within(document.querySelector('.table') as HTMLElement)
const lapRows = () => document.querySelectorAll('.table tbody tr').length

beforeEach(() => {
  vi.useFakeTimers()
  vi.resetAllMocks()
  catalog.mockResolvedValue({ tracks: CATALOG })
  status.mockResolvedValue(makeStatus())
  trackMap.mockResolvedValue({ track_id: 0, available: false, reason: 'no_positions', message: 'none', driver_path: null, centerline: { available: false }, laps: [], rejected: [] })
  lapPath.mockImplementation(async (id) => ({ lap_id: id, track_id: null, available: false, reason: 'no_positions', message: 'none' }))
  vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} })
})

afterEach(() => {
  cleanup()
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('LapComparisonPage circuits', () => {
  it('the selector receives several circuits and shows only the viewed circuit laps', async () => {
    laps.mockResolvedValue({ laps: [cotaLap, monzaLap, suzukaLap], skipped: [] })
    tracks.mockResolvedValue(makeTracks())
    render(<LapComparisonPage />)
    await flush()

    expect([...viewedSelect().options].map((o) => o.text)).toEqual(['Circuit of the Americas', 'Monza', 'Suzuka'])
    expect(viewedSelect().value).toBe('11') // nothing live: starts on the circuit with the most valid laps
    expect(lapsTable().getByText('1:20.000')).toBeTruthy() // Monza lap
    expect(lapsTable().queryByText('1:30.000')).toBeNull() // Suzuka lap is not on screen
    expect(lapRows()).toBe(1)

    fireEvent.change(viewedSelect(), { target: { value: '13' } })
    await flush()
    expect(lapsTable().getByText('1:30.000')).toBeTruthy()
    expect(lapsTable().queryByText('1:20.000')).toBeNull()
  })

  it('the live circuit is independent of the circuit being browsed', async () => {
    laps.mockResolvedValue({ laps: [cotaLap, monzaLap, suzukaLap], skipped: [] })
    tracks.mockResolvedValue(makeTracks({ active_track_id: 15 }))
    status.mockResolvedValue(recordingOn(15, 'Circuit of the Americas'))
    render(<LapComparisonPage />)
    await flush()

    // The live circuit is COTA, so that is what is shown first.
    const live = screen.getByLabelText('Live circuit')
    expect(within(live).getByText('Circuit of the Americas')).toBeTruthy()
    expect(viewedSelect().value).toBe('15')

    // Browsing Suzuka leaves the live circuit alone and says so.
    fireEvent.change(viewedSelect(), { target: { value: '13' } })
    await flush()
    expect(viewedSelect().value).toBe('13')
    expect(within(screen.getByLabelText('Live circuit')).getByText('Circuit of the Americas')).toBeTruthy()
    expect(within(screen.getByLabelText('Live circuit')).getByText(/different circuit than the live session/)).toBeTruthy()
  })

  it('follows a live circuit change until the user picks a circuit, then stops following', async () => {
    laps.mockResolvedValue({ laps: [cotaLap, monzaLap, suzukaLap], skipped: [] })
    tracks.mockResolvedValue(makeTracks({ active_track_id: 15 }))
    status.mockResolvedValue(recordingOn(15, 'Circuit of the Americas'))
    render(<LapComparisonPage />)
    await flush()
    expect(viewedSelect().value).toBe('15')

    status.mockResolvedValue(recordingOn(11, 'Monza')) // the game moves to Monza
    await flush(1000)
    expect(within(screen.getByLabelText('Live circuit')).getByText('Monza')).toBeTruthy()
    expect(viewedSelect().value).toBe('11') // not picked yet: the view follows the live circuit

    fireEvent.change(viewedSelect(), { target: { value: '13' } }) // the user picks Suzuka
    status.mockResolvedValue(recordingOn(15, 'Circuit of the Americas')) // and the game goes back to COTA
    await flush(1000)
    expect(within(screen.getByLabelText('Live circuit')).getByText('Circuit of the Americas')).toBeTruthy()
    expect(viewedSelect().value).toBe('13') // the pick is kept
  })

  it('a circuit change does not need a page refresh: the list is refetched for the new live circuit', async () => {
    laps.mockResolvedValue({ laps: [cotaLap], skipped: [] })
    tracks.mockResolvedValue(makeTracks({ tracks: [makeTracks().tracks[0]], active_track_id: 15 }))
    status.mockResolvedValue(recordingOn(15, 'Circuit of the Americas'))
    render(<LapComparisonPage />)
    await flush()
    const before = tracks.mock.calls.length

    tracks.mockResolvedValue(makeTracks({ active_track_id: 13 })) // a Suzuka profile now exists
    status.mockResolvedValue(recordingOn(13, 'Suzuka'))
    await flush(1000)
    expect(tracks.mock.calls.length).toBeGreaterThan(before)
    expect([...viewedSelect().options].map((o) => o.text)).toContain('Suzuka (live)')
  })
})

describe('LapComparisonPage legacy laps', () => {
  it('laps without a circuit appear as unassigned and are never assigned automatically', async () => {
    laps.mockResolvedValue({ laps: [legacyLap], skipped: [] })
    tracks.mockResolvedValue(makeTracks({ tracks: [], unassigned_laps: 1 }))
    render(<LapComparisonPage />)
    await flush()

    expect(viewedSelect().value).toBe('unassigned')
    expect(screen.getByText(/1 lap recorded before circuit identification/)).toBeTruthy()
    expect(screen.getByLabelText('Circuit for lap 1')).toBeTruthy()
    expect(assign).not.toHaveBeenCalled()
  })

  it('assigning a legacy lap calls the API once and then refreshes laps and circuits', async () => {
    laps.mockResolvedValue({ laps: [legacyLap], skipped: [] })
    tracks.mockResolvedValue(makeTracks({ tracks: [], unassigned_laps: 1 }))
    assign.mockResolvedValue({ track_id: 15, track_name: 'Circuit of the Americas', track_source: 'manual' })
    render(<LapComparisonPage />)
    await flush()
    const lapCalls = laps.mock.calls.length
    const trackCalls = tracks.mock.calls.length

    laps.mockResolvedValue({ laps: [{ ...legacyLap, track_id: 15, track_name: 'Circuit of the Americas', track_source: 'manual' }], skipped: [] })
    tracks.mockResolvedValue(makeTracks({ tracks: [makeTracks().tracks[0]], unassigned_laps: 0 }))
    fireEvent.change(screen.getByLabelText('Circuit for lap 1'), { target: { value: '15' } })
    fireEvent.click(screen.getByRole('button', { name: 'Assign lap 1' }))
    await flush()

    expect(assign).toHaveBeenCalledTimes(1)
    expect(assign).toHaveBeenCalledWith('old_lap01', 15)
    expect(laps.mock.calls.length).toBeGreaterThan(lapCalls)
    expect(tracks.mock.calls.length).toBeGreaterThan(trackCalls)
    expect(viewedSelect().value).toBe('15') // the lap now belongs to COTA, which is shown
  })

  it('a failed assignment shows the reason and changes nothing', async () => {
    laps.mockResolvedValue({ laps: [legacyLap], skipped: [] })
    tracks.mockResolvedValue(makeTracks({ tracks: [], unassigned_laps: 1 }))
    assign.mockRejectedValue(new Error("this lap's circuit was reported by the game and cannot be changed"))
    render(<LapComparisonPage />)
    await flush()
    fireEvent.change(screen.getByLabelText('Circuit for lap 1'), { target: { value: '13' } })
    fireEvent.click(screen.getByRole('button', { name: 'Assign lap 1' }))
    await flush()
    expect(screen.getByText(/cannot be changed/)).toBeTruthy()
    expect(viewedSelect().value).toBe('unassigned')
  })

  it('mixes tagged and legacy laps: each is only in its own view', async () => {
    laps.mockResolvedValue({ laps: [cotaLap, legacyLap], skipped: [] })
    tracks.mockResolvedValue(makeTracks({ tracks: [makeTracks().tracks[0]], unassigned_laps: 1, active_track_id: 15 }))
    status.mockResolvedValue(recordingOn(15, 'Circuit of the Americas'))
    render(<LapComparisonPage />)
    await flush()
    expect(lapRows()).toBe(1)
    expect([...viewedSelect().options].map((o) => o.text)).toEqual(['Circuit of the Americas (live)', 'Unassigned laps (1)'])
    fireEvent.change(viewedSelect(), { target: { value: 'unassigned' } })
    await flush()
    expect(screen.getByLabelText('Circuit for lap 1')).toBeTruthy()
  })
})

describe('LapComparisonPage track map', () => {
  it('asks for the map of the viewed circuit and the selected laps, and never for another circuit', async () => {
    laps.mockResolvedValue({ laps: [cotaLap, monzaLap], skipped: [] })
    tracks.mockResolvedValue(makeTracks({ active_track_id: 15 }))
    status.mockResolvedValue(recordingOn(15, 'Circuit of the Americas'))
    render(<LapComparisonPage />)
    await flush()
    expect(screen.getByText('Track map')).toBeTruthy()
    expect(trackMap.mock.calls.every((c) => c[0] === 15)).toBe(true)
    expect(lapPath.mock.calls.map((c) => c[0])).toContain('cota_lap01')
    expect(lapPath.mock.calls.map((c) => c[0])).not.toContain('monza_lap01')

    fireEvent.change(viewedSelect(), { target: { value: '11' } })
    await flush()
    expect(trackMap).toHaveBeenLastCalledWith(11, expect.anything())
    expect(lapPath.mock.calls.map((c) => c[0])).toContain('monza_lap01')
  })

  it('shows the empty state for a circuit with no positions, and no map for unassigned laps', async () => {
    laps.mockResolvedValue({ laps: [cotaLap, legacyLap], skipped: [] })
    tracks.mockResolvedValue(makeTracks({ tracks: [makeTracks().tracks[0]], unassigned_laps: 1, active_track_id: 15 }))
    status.mockResolvedValue(recordingOn(15, 'Circuit of the Americas'))
    render(<LapComparisonPage />)
    await flush()
    expect(screen.getByText(/No position data for this circuit yet/)).toBeTruthy()
    fireEvent.change(viewedSelect(), { target: { value: 'unassigned' } })
    await flush()
    expect(screen.queryByText('Track map')).toBeNull()
  })
})
