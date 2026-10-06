import { useCallback, useEffect, useRef, useState } from 'react'
import { errorMessage } from '../api/client'

export type AsyncState<T> =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'error'; error: string }
  | { status: 'ready'; data: T }

/**
 * Runs an async function and tracks idle / loading / error / ready.
 * Starting a new run (or unmounting) aborts the previous one, so stale results never land.
 * `run` resolves to the data, or undefined if it failed or was superseded.
 */
export function useAsyncAction<A extends unknown[], T>(
  fn: (signal: AbortSignal, ...args: A) => Promise<T>,
) {
  const [state, setState] = useState<AsyncState<T>>({ status: 'idle' })
  const current = useRef<AbortController | null>(null)

  useEffect(() => () => current.current?.abort(), [])

  const run = useCallback(
    async (...args: A): Promise<T | undefined> => {
      current.current?.abort()
      const controller = new AbortController()
      current.current = controller
      setState({ status: 'loading' })
      try {
        const data = await fn(controller.signal, ...args)
        if (controller.signal.aborted) return undefined
        setState({ status: 'ready', data })
        return data
      } catch (e) {
        if (controller.signal.aborted) return undefined
        setState({ status: 'error', error: errorMessage(e) })
        return undefined
      }
    },
    [fn],
  )

  const reset = useCallback(() => {
    current.current?.abort()
    setState({ status: 'idle' })
  }, [])

  return { state, run, reset }
}
