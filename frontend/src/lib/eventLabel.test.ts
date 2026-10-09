import { describe, expect, it } from 'vitest'
import { cornerHint, eventLabel } from './eventLabel'
import { makeEvent } from './testData'

describe('eventLabel', () => {
  it('puts a confident corner first and keeps the event number', () => {
    expect(eventLabel(makeEvent({ corner_label: 'T11', event_number: 4 }))).toBe('T11 · Event 4')
    expect(eventLabel(makeEvent({ corner_label: 'T3-T6', event_number: 2 }))).toBe('T3-T6 · Event 2')
  })

  it('falls back to the generic event name when no corner is identified', () => {
    expect(eventLabel(makeEvent({ corner_label: null, event_number: 4 }))).toBe('Event 4')
    expect(eventLabel(makeEvent({ corner_label: null, corner_status: 'uncertain', event_number: 7 }))).toBe('Event 7')
  })

  it('explains uncertain and confident corners in the tooltip', () => {
    const uncertain = makeEvent({ corner_status: 'uncertain', corner_candidates: ['T7', 'T8'], corner_reason: 'the event spans more than one corner' })
    expect(cornerHint(uncertain)).toContain('T7, T8')
    expect(cornerHint(makeEvent({ corner_label: 'T1', corner_status: 'single', corner_confidence: 0.96 }))).toContain('96%')
    expect(cornerHint(makeEvent())).toBeUndefined()
  })
})
