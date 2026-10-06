import type { CompareResponse } from '../../api/types'
import { Notice, Readout } from '../../design'
import { deltaTone, fmtMeters, fmtSeconds, shortSession } from '../../lib/format'

function lapLabel(lap: CompareResponse['reference']) {
  return `Lap ${lap.lap_number} · session ${shortSession(lap.session_uid)}`
}

export function Summary({ result }: { result: CompareResponse }) {
  const { summary: s, reference, comparison } = result
  const total = s.total_difference_ms
  const totalMs = total ?? s.final_delta_ms
  const shared = s.end_distance_m - s.start_distance_m

  return (
    <div className="stack">
      {result.warnings.length > 0 && (
        <Notice tone="warn" title="Warnings">
          <ul>{result.warnings.map((w) => <li key={w}>{w}</li>)}</ul>
        </Notice>
      )}
      <div className="panel">
        <div className="readouts">
          <Readout label="Reference lap" value={reference.lap_time ?? '—'} sub={lapLabel(reference)} />
          <Readout label="Comparison lap" value={comparison.lap_time ?? '—'} sub={lapLabel(comparison)} />
          <Readout
            label="Total delta"
            value={fmtSeconds(totalMs)}
            tone={deltaTone(totalMs)}
            sub={total === null
              ? `at ${fmtMeters(s.final_distance_m)} (a lap time is unknown)`
              : '+ comparison slower / − faster'}
          />
          <Readout
            label="Largest gain"
            value={s.largest_gain ? fmtSeconds(s.largest_gain.delta_ms) : 'None'}
            tone={s.largest_gain ? 'gain' : 'neutral'}
            sub={s.largest_gain ? `at ${fmtMeters(s.largest_gain.distance_m)}` : 'never ahead of reference'}
          />
          <Readout
            label="Largest loss"
            value={s.largest_loss ? fmtSeconds(s.largest_loss.delta_ms) : 'None'}
            tone={s.largest_loss ? 'loss' : 'neutral'}
            sub={s.largest_loss ? `at ${fmtMeters(s.largest_loss.distance_m)}` : 'never behind reference'}
          />
          <Readout
            label="Shared distance"
            value={`${fmtMeters(shared)}`}
            sub={`${fmtMeters(s.start_distance_m)} to ${fmtMeters(s.end_distance_m)} · ${s.points} points`}
          />
        </div>
      </div>
    </div>
  )
}
