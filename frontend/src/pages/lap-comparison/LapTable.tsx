import type { LapMeta } from '../../api/types'
import { Badge, Button, Table, Td, Th } from '../../design'
import { fmtMeters, shortSession } from '../../lib/format'

export function LapTable(props: {
  laps: LapMeta[]
  refId: string | null
  cmpId: string | null
  onSelectRef: (id: string) => void
  onSelectCmp: (id: string) => void
}) {
  return (
    <Table caption="Recorded laps">
      <thead>
        <tr>
          <Th>Session</Th>
          <Th numeric>Lap</Th>
          <Th numeric>Time</Th>
          <Th>Status</Th>
          <Th numeric>Samples</Th>
          <Th numeric>Distance</Th>
          <Th>Use as</Th>
        </tr>
      </thead>
      <tbody>
        {props.laps.map((lap) => (
          <tr key={lap.id} className={lap.valid ? undefined : 'is-dim'}>
            <Td><span className="mono">{shortSession(lap.session_uid)}</span></Td>
            <Td numeric>{lap.lap_number}</Td>
            <Td numeric>{lap.lap_time ?? '—'}</Td>
            <Td>
              {lap.valid
                ? <Badge>Valid</Badge>
                : <Badge tone="warn" title="Track limits were exceeded on this lap">Invalid</Badge>}
            </Td>
            <Td numeric>{lap.samples}</Td>
            <Td numeric>{fmtMeters(lap.start_distance_m)} to {fmtMeters(lap.end_distance_m)}</Td>
            <Td>
              <span className="row row--tight">
                <Button size="sm" variant="toggle" pressed={props.refId === lap.id}
                  onClick={() => props.onSelectRef(lap.id)}
                  aria-label={`Use lap ${lap.lap_number} as reference`}>Ref</Button>
                <Button size="sm" variant="toggle" pressed={props.cmpId === lap.id}
                  onClick={() => props.onSelectCmp(lap.id)}
                  aria-label={`Use lap ${lap.lap_number} as comparison`}>Cmp</Button>
              </span>
            </Td>
          </tr>
        ))}
      </tbody>
    </Table>
  )
}
