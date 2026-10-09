import { useState } from 'react'
import type { CatalogTrack, LapMeta } from '../../api/types'
import { Button, Table, Td, Th } from '../../design'
import { fmtMeters, shortSession } from '../../lib/format'
import { catalogLabel } from '../../lib/tracks'

/** Present only when viewing laps with no known circuit: lets the user assign each one. */
export interface AssignProps {
  catalog: CatalogTrack[]
  onAssign: (lapId: string, trackId: number) => Promise<void> | void
}

/** "Assign to [circuit] [Assign]" for one lap. Nothing is assigned until the button is pressed. */
function AssignCell({ lap, assign }: { lap: LapMeta; assign: AssignProps }) {
  const [choice, setChoice] = useState('')
  const [busy, setBusy] = useState(false)
  return (
    <span className="row row--tight">
      <select className="select" aria-label={`Circuit for lap ${lap.lap_number}`} value={choice}
        onChange={(e) => setChoice(e.target.value)}>
        <option value="">Circuit...</option>
        {assign.catalog.map((t) => <option key={t.track_id} value={t.track_id}>{catalogLabel(t)}</option>)}
      </select>
      <Button size="sm" disabled={choice === '' || busy} aria-label={`Assign lap ${lap.lap_number}`}
        onClick={async () => {
          setBusy(true)
          try {
            await assign.onAssign(lap.id, Number(choice))
          } finally {
            setBusy(false)
          }
        }}>Assign</Button>
    </span>
  )
}

export function LapTable(props: {
  laps: LapMeta[]
  refId: string | null
  cmpId: string | null
  onSelectRef: (id: string) => void
  onSelectCmp: (id: string) => void
  assign?: AssignProps
}) {
  const compact = props.assign !== undefined // room is needed for the assignment controls
  return (
    <Table caption="Recorded laps">
      <thead>
        <tr>
          <Th numeric>Lap</Th>
          <Th numeric>Time</Th>
          <Th>Status</Th>
          <Th>Session</Th>
          {!compact && <Th numeric>Samples</Th>}
          {!compact && <Th numeric>Distance</Th>}
          <Th>Use as</Th>
          {compact && <Th>Assign track</Th>}
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
              {!compact && <Td numeric><span className="text-dim">{lap.samples}</span></Td>}
              {!compact && <Td numeric><span className="text-dim">{Math.round(lap.start_distance_m)}&ndash;{fmtMeters(lap.end_distance_m)}</span></Td>}
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
              {props.assign && <Td><AssignCell lap={lap} assign={props.assign} /></Td>}
            </tr>
          )
        })}
      </tbody>
    </Table>
  )
}
