import type { LapMeta } from '../../api/types'
import { Button, Table, Td, Th } from '../../design'
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
          <Th numeric>Lap</Th>
          <Th numeric>Time</Th>
          <Th>Status</Th>
          <Th>Session</Th>
          <Th numeric>Samples</Th>
          <Th numeric>Distance</Th>
          <Th>Use as</Th>
        </tr>
      </thead>
      <tbody>
        {props.laps.map((lap) => {
          const role = lap.id === props.refId ? 'is-ref' : lap.id === props.cmpId ? 'is-cmp' : ''
          return (
            <tr key={lap.id} className={[lap.valid ? '' : 'is-dim', role && 'is-selected', role].filter(Boolean).join(' ') || undefined}>
              <Td numeric>{lap.lap_number}</Td>
              <Td numeric><span className="lap-time">{lap.lap_time ?? '—'}</span></Td>
              <Td>
                <span className={`status ${lap.valid ? 'status--valid' : 'status--invalid'}`}
                  title={lap.valid ? undefined : 'Track limits were exceeded on this lap'}>
                  {lap.valid ? 'Valid' : 'Invalid'}
                </span>
              </Td>
              <Td><span className="mono text-dim">{shortSession(lap.session_uid)}</span></Td>
              <Td numeric><span className="text-dim">{lap.samples}</span></Td>
              <Td numeric><span className="text-dim">{Math.round(lap.start_distance_m)}&ndash;{fmtMeters(lap.end_distance_m)}</span></Td>
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
          )
        })}
      </tbody>
    </Table>
  )
}
