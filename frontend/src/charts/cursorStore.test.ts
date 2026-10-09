import { describe, expect, it, vi } from 'vitest'
import { createCursorStore } from './cursorStore'

describe('cursor store', () => {
  it('starts empty and notifies subscribers only on change', () => {
    const store = createCursorStore()
    const listener = vi.fn()
    store.subscribe(listener)
    expect(store.get()).toBeNull()

    store.set(5)
    store.set(5) // same value: no notification
    expect(store.get()).toBe(5)
    expect(listener).toHaveBeenCalledTimes(1)

    store.set(null)
    expect(listener).toHaveBeenCalledTimes(2)
  })

  it('stops notifying after unsubscribe', () => {
    const store = createCursorStore()
    const listener = vi.fn()
    const unsubscribe = store.subscribe(listener)
    unsubscribe()
    store.set(1)
    expect(listener).not.toHaveBeenCalled()
  })

  it('forwards a focus request (lap distance) to every chart until unsubscribed', () => {
    const store = createCursorStore()
    const a = vi.fn()
    const b = vi.fn()
    const offA = store.onFocus(a)
    store.onFocus(b)
    store.focus(1234)
    expect(a).toHaveBeenCalledWith(1234)
    expect(b).toHaveBeenCalledWith(1234)
    offA()
    store.focus(10)
    expect(a).toHaveBeenCalledTimes(1)
    expect(b).toHaveBeenCalledTimes(2)
  })
})
