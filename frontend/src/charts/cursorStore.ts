import { useSyncExternalStore } from 'react'

/**
 * Holds the data index under the synchronized chart cursor (null when the pointer is outside).
 * Charts publish into it; small readout components subscribe. The charts themselves never
 * re-render on mouse move.
 */
export interface CursorStore {
  get: () => number | null
  set: (index: number | null) => void
  subscribe: (listener: () => void) => () => void
  /** Ask every chart to move its cursor to a lap distance (used when a point on the track map is clicked). */
  focus: (distance: number) => void
  onFocus: (listener: (distance: number) => void) => () => void
}

export function createCursorStore(): CursorStore {
  let index: number | null = null
  const listeners = new Set<() => void>()
  const focusListeners = new Set<(distance: number) => void>()
  return {
    get: () => index,
    set(next) {
      if (next === index) return
      index = next
      listeners.forEach((l) => l())
    },
    subscribe(listener) {
      listeners.add(listener)
      return () => {
        listeners.delete(listener)
      }
    },
    focus(distance) {
      focusListeners.forEach((l) => l(distance))
    },
    onFocus(listener) {
      focusListeners.add(listener)
      return () => {
        focusListeners.delete(listener)
      }
    },
  }
}

export const useCursorIndex = (store: CursorStore) => useSyncExternalStore(store.subscribe, store.get)
