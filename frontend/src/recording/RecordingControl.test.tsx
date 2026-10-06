// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { RecordingControl, type RecordingControlProps } from './RecordingControl'
import { makeStatus } from './testStatus'

afterEach(cleanup)

function setup(overrides: Partial<RecordingControlProps> = {}) {
  const props: RecordingControlProps = {
    status: makeStatus(),
    reachable: true,
    busy: false,
    actionError: null,
    onStart: vi.fn(),
    onStop: vi.fn(),
    ...overrides,
  }
  render(<RecordingControl {...props} />)
  return props
}

describe('RecordingControl', () => {
  it('idle: shows Start Recording and starts on click', () => {
    const props = setup()
    expect(screen.getByText('Idle').getAttribute('aria-current')).toBe('true')
    expect(screen.queryByText('Stop Recording')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Start Recording' }))
    expect(props.onStart).toHaveBeenCalledTimes(1)
  })

  it('recording: shows Stop Recording, packet rate, lap and saved count', () => {
    const props = setup({
      status: makeStatus({ state: 'recording', running: true, receiving: true, packets_per_second: 600, current_lap: 2, laps_saved: 1 }),
    })
    expect(screen.queryByText('Start Recording')).toBeNull()
    expect(screen.getByText('Recording').getAttribute('aria-current')).toBe('true')
    expect(screen.getByText('Receiving 600 pkt/s')).toBeTruthy()
    expect(screen.getByText('Lap 2')).toBeTruthy()
    expect(screen.getByText('1 saved')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Stop Recording' }))
    expect(props.onStop).toHaveBeenCalledTimes(1)
  })

  it('waiting: says no packets are arriving', () => {
    setup({ status: makeStatus({ state: 'waiting', running: true }) })
    expect(screen.getByText('Waiting').getAttribute('aria-current')).toBe('true')
    expect(screen.getByText('Idle').getAttribute('aria-current')).toBeNull()
    expect(screen.getByText('No packets')).toBeTruthy()
  })

  it('disables the buttons while a request is in flight', () => {
    setup({ busy: true })
    expect((screen.getByRole('button', { name: 'Start Recording' }) as HTMLButtonElement).disabled).toBe(true)
  })

  it('cannot start when the API is offline', () => {
    setup({ status: null, reachable: false })
    expect(screen.getByText('API offline')).toBeTruthy()
    expect((screen.getByRole('button', { name: 'Start Recording' }) as HTMLButtonElement).disabled).toBe(true)
  })

  it('shows an action error or the last recording error', () => {
    setup({ actionError: 'a recording is already running' })
    expect(screen.getByText('a recording is already running')).toBeTruthy()
    cleanup()
    setup({ status: makeStatus({ state: 'error', last_error: 'cannot listen on UDP port 20777' }) })
    expect(screen.getByText('Error')).toBeTruthy()
    expect(screen.getByText('cannot listen on UDP port 20777')).toBeTruthy()
  })
})
