// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { makeEvent } from '../../lib/testData'
import { EventsTable } from './EventsTable'

afterEach(cleanup)

describe('EventsTable', () => {
  it('shows "T11 · Event 4" for a mapped corner and plain "Event N" otherwise', () => {
    render(<EventsTable events={[
      makeEvent({ name: 'Event 1', event_number: 1, corner_label: 'T1', corner_status: 'single', corner_confidence: 0.96 }),
      makeEvent({ name: 'Event 2', event_number: 2, corner_label: 'T3-T6', corner_status: 'complex', corner_confidence: 0.8 }),
      makeEvent({ name: 'Event 3', event_number: 3 }),
      makeEvent({ name: 'Event 4', event_number: 4, corner_status: 'uncertain', corner_candidates: ['T7', 'T8'], corner_reason: 'spans corners' }),
    ]} />)
    expect(screen.getByText('T1 · Event 1')).toBeTruthy()
    expect(screen.getByText('T3-T6 · Event 2')).toBeTruthy()
    expect(screen.getByText('Event 3')).toBeTruthy()
    const uncertain = screen.getByText('Event 4')
    expect(uncertain.getAttribute('title')).toContain('T7, T8')
  })

  it('keeps ambiguous generic matches ambiguous, with or without a corner label', () => {
    render(<EventsTable events={[
      makeEvent({
        name: 'Event 3', event_number: 3, status: 'ambiguous', corner_label: 'T4', corner_status: 'single',
        corner_confidence: 0.4, note: 'throttle pickup differs by 150 m', brake_start_diff_m: null,
      }),
    ]} />)
    expect(screen.getByText('T4 · Event 3')).toBeTruthy()
    expect(screen.getByText('Ambiguous')).toBeTruthy()
    expect(screen.getAllByText('?').length).toBeGreaterThan(0) // no braking/throttle comparison
  })
})
