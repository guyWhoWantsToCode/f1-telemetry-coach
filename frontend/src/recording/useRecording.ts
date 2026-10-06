import { useCallback, useEffect, useRef, useState } from 'react'
import { errorMessage, getRecordingStatus, startRecording, stopRecording } from '../api/client'
import type { RecordingStatus } from '../api/types'

const POLL_ACTIVE_MS = 1000 // while listening: packet rate and lap should feel current
const POLL_IDLE_MS = 3000

/**
 * Polls the recording status and exposes start/stop.
 * `onLapsChanged` fires after a recording stops and whenever a new lap was saved, so the
 * caller can refresh its recorded-laps list.
 */
export function useRecording(onLapsChanged: () => void) {
  const [status, setStatus] = useState<RecordingStatus | null>(null)
  const [reachable, setReachable] = useState(true)
  const [busy, setBusy] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)

  const previous = useRef<RecordingStatus | null>(null)
  const callback = useRef(onLapsChanged)
  useEffect(() => {
    callback.current = onLapsChanged
  }, [onLapsChanged])

  /** Single entry point for every status (poll or action reply), so laps changes fire once. */
  const apply = useCallback((next: RecordingStatus) => {
    const prev = previous.current
    previous.current = next
    setStatus(next)
    setReachable(true)
    if (prev && (next.laps_saved > prev.laps_saved || (prev.running && !next.running))) callback.current()
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    let timer: ReturnType<typeof setTimeout> | undefined

    const poll = async () => {
      try {
        apply(await getRecordingStatus(controller.signal))
      } catch {
        if (controller.signal.aborted) return
        setReachable(false)
      }
      if (controller.signal.aborted) return
      timer = setTimeout(() => void poll(), previous.current?.running ? POLL_ACTIVE_MS : POLL_IDLE_MS)
    }
    void poll()

    return () => {
      controller.abort()
      clearTimeout(timer)
    }
  }, [apply])

  const act = useCallback(
    async (action: () => Promise<RecordingStatus>) => {
      setBusy(true)
      setActionError(null)
      try {
        apply(await action())
      } catch (e) {
        setActionError(errorMessage(e))
        try {
          apply(await getRecordingStatus())
        } catch {
          setReachable(false)
        }
      } finally {
        setBusy(false)
      }
    },
    [apply],
  )

  const start = useCallback(() => act(startRecording), [act])
  const stop = useCallback(() => act(stopRecording), [act])

  return { status, reachable, busy, actionError, start, stop }
}
