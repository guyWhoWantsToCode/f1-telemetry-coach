// @vitest-environment jsdom
import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { getRecordingStatus, startRecording, stopRecording } from '../api/client'
import { makeStatus } from './testStatus'
import { useRecording } from './useRecording'

vi.mock('../api/client', () => ({
  getRecordingStatus: vi.fn(),
  startRecording: vi.fn(),
  stopRecording: vi.fn(),
  errorMessage: (e: unknown) => (e instanceof Error ? e.message : String(e)),
}))

const getStatus = vi.mocked(getRecordingStatus)
const start = vi.mocked(startRecording)
const stop = vi.mocked(stopRecording)

const running = (overrides = {}) => makeStatus({ state: 'recording', running: true, receiving: true, ...overrides })

async function flush(ms = 0) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms)
  })
}

beforeEach(() => {
  vi.useFakeTimers()
  vi.resetAllMocks()
})

afterEach(() => {
  cleanup()
  vi.useRealTimers()
})

describe('useRecording', () => {
  it('loads the status immediately and then polls (1 s while recording)', async () => {
    getStatus.mockResolvedValue(running())
    const { result } = renderHook(() => useRecording(vi.fn()))
    await flush()
    expect(result.current.status?.state).toBe('recording')
    expect(getStatus).toHaveBeenCalledTimes(1)

    await flush(1000)
    expect(getStatus).toHaveBeenCalledTimes(2)
    await flush(1000)
    expect(getStatus).toHaveBeenCalledTimes(3)
  })

  it('polls more slowly while idle', async () => {
    getStatus.mockResolvedValue(makeStatus())
    renderHook(() => useRecording(vi.fn()))
    await flush()
    await flush(1000)
    expect(getStatus).toHaveBeenCalledTimes(1)
    await flush(2000)
    expect(getStatus).toHaveBeenCalledTimes(2)
  })

  it('marks the API unreachable when status fails, and recovers', async () => {
    getStatus.mockRejectedValueOnce(new Error('down')).mockResolvedValue(makeStatus())
    const { result } = renderHook(() => useRecording(vi.fn()))
    await flush()
    expect(result.current.reachable).toBe(false)
    await flush(3000)
    expect(result.current.reachable).toBe(true)
  })

  it('start() calls the API and shows the new status', async () => {
    getStatus.mockResolvedValue(makeStatus())
    start.mockResolvedValue(makeStatus({ state: 'waiting', running: true }))
    const { result } = renderHook(() => useRecording(vi.fn()))
    await flush()
    await act(async () => {
      await result.current.start()
    })
    expect(start).toHaveBeenCalledTimes(1)
    expect(result.current.status?.state).toBe('waiting')
    expect(result.current.actionError).toBeNull()
  })

  it('a rejected start shows the error and re-reads the real status', async () => {
    getStatus.mockResolvedValueOnce(makeStatus()).mockResolvedValue(makeStatus({ state: 'error', last_error: 'port busy' }))
    start.mockRejectedValue(new Error('cannot listen on UDP port 20777'))
    const { result } = renderHook(() => useRecording(vi.fn()))
    await flush()
    await act(async () => {
      await result.current.start()
    })
    expect(result.current.actionError).toBe('cannot listen on UDP port 20777')
    expect(result.current.status?.state).toBe('error')
    expect(result.current.busy).toBe(false)
  })

  it('refreshes the laps list once after stopping', async () => {
    const onLapsChanged = vi.fn()
    getStatus.mockResolvedValue(running({ laps_saved: 2 }))
    stop.mockResolvedValue(makeStatus({ laps_saved: 2 }))
    const { result } = renderHook(() => useRecording(onLapsChanged))
    await flush()
    expect(onLapsChanged).not.toHaveBeenCalled() // first status is not a change

    getStatus.mockResolvedValue(makeStatus({ laps_saved: 2 }))
    await act(async () => {
      await result.current.stop()
    })
    expect(stop).toHaveBeenCalledTimes(1)
    expect(onLapsChanged).toHaveBeenCalledTimes(1)
    await flush(3000) // the next poll sees the same idle status: no second refresh
    expect(onLapsChanged).toHaveBeenCalledTimes(1)
  })

  it('refreshes the laps list when a new lap is saved while recording', async () => {
    const onLapsChanged = vi.fn()
    getStatus.mockResolvedValue(running({ laps_saved: 0 }))
    renderHook(() => useRecording(onLapsChanged))
    await flush()
    getStatus.mockResolvedValue(running({ laps_saved: 1 }))
    await flush(1000)
    expect(onLapsChanged).toHaveBeenCalledTimes(1)
    await flush(1000) // unchanged count: no further refresh
    expect(onLapsChanged).toHaveBeenCalledTimes(1)
  })

  it('refreshes when the recording stops from elsewhere', async () => {
    const onLapsChanged = vi.fn()
    getStatus.mockResolvedValue(running())
    renderHook(() => useRecording(onLapsChanged))
    await flush()
    getStatus.mockResolvedValue(makeStatus())
    await flush(1000)
    expect(onLapsChanged).toHaveBeenCalledTimes(1)
  })

  it('stops polling after unmount', async () => {
    getStatus.mockResolvedValue(makeStatus())
    const { unmount } = renderHook(() => useRecording(vi.fn()))
    await flush()
    unmount()
    await flush(10000)
    expect(getStatus).toHaveBeenCalledTimes(1)
  })
})
