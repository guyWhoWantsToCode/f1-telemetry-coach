// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { makeTracks } from '../lib/testData'
import { UNASSIGNED } from '../lib/tracks'
import { makeStatus } from '../recording/testStatus'
import { TrackBar, type TrackBarProps } from './TrackBar'

afterEach(cleanup)

function setup(overrides: Partial<TrackBarProps> = {}) {
  const props: TrackBarProps = {
    tracks: makeTracks(),
    loading: false,
    error: null,
    viewing: 15,
    onView: vi.fn(),
    recording: makeStatus(),
    ...overrides,
  }
  render(<TrackBar {...props} />)
  return props
}

const recordingOn = (trackId: number | null, name: string | null) =>
  makeStatus({
    state: 'recording', running: true, receiving: true, active_track_id: trackId, active_track_name: name,
    track_length_m: trackId === null ? null : 5513, session_type_name: trackId === null ? null : 'Time Trial',
  })

describe('TrackBar', () => {
  it('the selector lists every circuit the application knows', () => {
    setup()
    const select = screen.getByLabelText('Circuit being viewed') as HTMLSelectElement
    expect([...select.options].map((o) => o.text)).toEqual(['Circuit of the Americas', 'Monza', 'Suzuka'])
    expect(select.value).toBe('15')
  })

  it('shows the viewed circuit history: PB, valid laps, sessions and corner status', () => {
    setup()
    expect(screen.getByText(/PB 1:40\.000/)).toBeTruthy()
    expect(screen.getByText(/3 valid laps/)).toBeTruthy()
    expect(screen.getByText(/1 session\b/)).toBeTruthy()
    expect(screen.getByText(/20 corners \(distances not calibrated\)/)).toBeTruthy()
  })

  it('a circuit with no history shows no invented data', () => {
    setup({ viewing: 13 })
    const text = screen.getByRole('group', { name: 'Circuit' }).textContent ?? ''
    expect(text).toContain('no PB')
    expect(text).toContain('0 valid laps')
    expect(text).toContain('no corner data')
  })

  it('choosing a circuit reports the choice and nothing else', () => {
    const props = setup()
    fireEvent.change(screen.getByLabelText('Circuit being viewed'), { target: { value: '11' } })
    expect(props.onView).toHaveBeenCalledTimes(1)
    expect(props.onView).toHaveBeenCalledWith(11)
  })

  it('live and viewed circuits are shown separately and a mismatch is flagged', () => {
    setup({ viewing: 13, recording: recordingOn(15, 'Circuit of the Americas') })
    const live = screen.getByLabelText('Live circuit')
    expect(within(live).getByText('Circuit of the Americas')).toBeTruthy()
    expect(within(live).getByText(/different circuit than the live session/)).toBeTruthy()
    expect((screen.getByLabelText('Circuit being viewed') as HTMLSelectElement).value).toBe('13') // still viewing Suzuka
  })

  it('no mismatch flag when viewing the live circuit, and the live circuit is marked in the list', () => {
    setup({ viewing: 15, recording: recordingOn(15, 'Circuit of the Americas') })
    expect(screen.queryByText(/different circuit than the live session/)).toBeNull()
    const select = screen.getByLabelText('Circuit being viewed') as HTMLSelectElement
    expect([...select.options].map((o) => o.text)[0]).toBe('Circuit of the Americas (live)')
  })

  it('live indicator when not recording or still waiting for the Session packet', () => {
    setup({ recording: makeStatus() })
    expect(within(screen.getByLabelText('Live circuit')).getByText('not recording')).toBeTruthy()
    cleanup()
    setup({ recording: recordingOn(null, null) })
    expect(within(screen.getByLabelText('Live circuit')).getByText('waiting for session data')).toBeTruthy()
  })

  it('an unrecognised live circuit keeps its number in the name', () => {
    setup({ recording: recordingOn(99, 'Unknown track (99)'), viewing: 15 })
    expect(within(screen.getByLabelText('Live circuit')).getByText('Unknown track (99)')).toBeTruthy()
  })

  it('offers unassigned laps as a separate view', () => {
    const props = setup({ tracks: makeTracks({ unassigned_laps: 9 }), viewing: UNASSIGNED })
    expect(screen.getByText(/9 laps recorded before circuit identification/)).toBeTruthy()
    const select = screen.getByLabelText('Circuit being viewed') as HTMLSelectElement
    expect(select.value).toBe('unassigned')
    expect([...select.options].map((o) => o.text)).toContain('Unassigned laps (9)')
    expect(props.onView).not.toHaveBeenCalled()
  })

  it('loading, error and empty states', () => {
    setup({ tracks: null, loading: true, viewing: null })
    expect(screen.getByText('Loading circuits...')).toBeTruthy()
    cleanup()
    setup({ tracks: null, error: 'Cannot reach the API', viewing: null })
    expect(screen.getByText('Cannot reach the API')).toBeTruthy()
    cleanup()
    setup({ tracks: makeTracks({ tracks: [], unassigned_laps: 0 }), viewing: null })
    expect(screen.getByText(/No circuits yet/)).toBeTruthy()
    expect((screen.getByLabelText('Circuit being viewed') as HTMLSelectElement).disabled).toBe(true)
  })
})
