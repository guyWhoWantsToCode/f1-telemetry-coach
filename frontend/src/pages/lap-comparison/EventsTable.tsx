import type { EventRow, EventStatus } from '../../api/types'
import { Badge, Table, Td, Th } from '../../design'
import { deltaTone, fmtMeters, fmtSeconds, fmtSigned } from '../../lib/format'

const STATE_LABEL: Record<EventStatus, string> = {
  matched: 'Matched',
  grouped: 'Grouped',
  ambiguous: 'Ambiguous',
  ref_only: 'Ref only',
  cmp_only: 'Cmp only',
}

function StateBadge({ row }: { row: EventRow }) {
  const label = row.status === 'grouped'
    ? `Grouped ${row.ref_events.length}:${row.cmp_events.length}`
    : STATE_LABEL[row.status]
  const title = row.status === 'grouped'
    ? `${row.ref_events.length} reference event(s) compared with ${row.cmp_events.length} comparison event(s) as one sequence`
    : row.note || undefined
  return <Badge tone={row.status === 'ambiguous' ? 'warn' : 'neutral'} title={title}>{label}</Badge>
}

/** A difference cell: "?" when the match is ambiguous, an em dash when there is nothing to compare. */
function diff(row: EventRow, value: number | null, unit: string, digits = 0) {
  return row.status === 'ambiguous' ? '?' : fmtSigned(value, unit, digits)
}

export function EventsTable({ events }: { events: EventRow[] }) {
  return (
    <Table caption="Detected corner and braking events">
      <thead>
        <tr>
          <Th numeric>#</Th>
          <Th numeric>Distance</Th>
          <Th numeric title="Comparison minus reference through the event. Positive = comparison lost time.">Time</Th>
          <Th numeric title="Negative = comparison braked earlier, positive = later">Braking</Th>
          <Th numeric title="Positive = comparison had a higher minimum speed">Min speed</Th>
          <Th numeric title="Negative = comparison picked up throttle earlier">Throttle</Th>
          <Th numeric title="Negative = comparison reached full throttle earlier">Full throttle</Th>
          <Th>State</Th>
        </tr>
      </thead>
      <tbody>
        {events.map((row) => {
          const hasNote = row.status === 'ambiguous' && row.note !== ''
          return (
            <EventRowView key={row.name} row={row} hasNote={hasNote} />
          )
        })}
      </tbody>
    </Table>
  )
}

function EventRowView({ row, hasNote }: { row: EventRow; hasNote: boolean }) {
  const number = row.name.replace(/^Event\s*/, '')
  return (
    <>
      <tr className={hasNote ? 'has-note' : undefined}>
        <Td numeric>{number}</Td>
        <Td numeric>{fmtMeters(row.position_m)}</Td>
        <Td numeric tone={deltaTone(row.time_delta_ms)}>
          {row.time_delta_ms === null ? '—' : fmtSeconds(row.time_delta_ms)}
        </Td>
        <Td numeric>{diff(row, row.brake_start_diff_m, 'm')}</Td>
        <Td numeric>{diff(row, row.min_speed_diff_kmh, 'km/h', 1)}</Td>
        <Td numeric>{diff(row, row.pickup_diff_m, 'm')}</Td>
        <Td numeric>{diff(row, row.full_throttle_diff_m, 'm')}</Td>
        <Td><StateBadge row={row} /></Td>
      </tr>
      {hasNote && (
        <tr>
          <Td note colSpan={8}>Ambiguous: {row.note}. Time is measured over the whole section by distance.</Td>
        </tr>
      )}
    </>
  )
}
