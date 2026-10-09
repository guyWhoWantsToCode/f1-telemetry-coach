import type { EventRow } from '../api/types'

/** "T11 · Event 4" when a corner is identified with confidence, otherwise just "Event 4". */
export function eventLabel(row: Pick<EventRow, 'corner_label' | 'event_number'>): string {
  return row.corner_label ? `${row.corner_label} · Event ${row.event_number}` : `Event ${row.event_number}`
}

/** Tooltip for an event whose corner could not be identified (or was identified with caveats). */
export function cornerHint(row: EventRow): string | undefined {
  if (row.corner_status === 'uncertain') {
    const candidates = row.corner_candidates.length > 0 ? ` (${row.corner_candidates.join(', ')})` : ''
    return `Corner uncertain${candidates}: ${row.corner_reason}`
  }
  if (row.corner_label && row.corner_confidence !== null) {
    return `Corner ${row.corner_label}, confidence ${Math.round(row.corner_confidence * 100)}%`
  }
  return undefined
}
