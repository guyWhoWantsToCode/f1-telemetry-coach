/*
 * Validates the aligned comparison columns from the API and shapes them for charting.
 * Nothing is recalculated: only display unit scaling (throttle/brake 0-1 -> %, delta ms -> s).
 */

export class ChartDataError extends Error {
  kind: 'empty' | 'malformed'

  constructor(kind: 'empty' | 'malformed', message: string) {
    super(message)
    this.name = 'ChartDataError'
    this.kind = kind
  }
}

export interface ChartData {
  distance: number[] // m
  speed: { ref: number[]; cmp: number[] } // km/h
  throttle: { ref: number[]; cmp: number[] } // %
  brake: { ref: number[]; cmp: number[] } // %
  delta: number[] // s, positive = comparison slower
}

const REQUIRED = [
  'distance_m',
  'delta_ms',
  'ref_speed_kmh',
  'cmp_speed_kmh',
  'ref_throttle',
  'cmp_throttle',
  'ref_brake',
  'cmp_brake',
] as const

type Column = (typeof REQUIRED)[number]

function column(raw: Record<string, unknown>, name: Column): number[] {
  const values = raw[name]
  if (!Array.isArray(values)) throw new ChartDataError('malformed', `Column "${name}" is missing`)
  for (let i = 0; i < values.length; i++) {
    if (typeof values[i] !== 'number' || !Number.isFinite(values[i])) {
      throw new ChartDataError('malformed', `Column "${name}" has a non-numeric value at row ${i + 1}`)
    }
  }
  return values as number[]
}

export function toChartData(raw: unknown): ChartData {
  if (typeof raw !== 'object' || raw === null || Array.isArray(raw)) {
    throw new ChartDataError('malformed', 'Comparison data is not an object')
  }
  const data = raw as Record<string, unknown>
  const cols = Object.fromEntries(REQUIRED.map((name) => [name, column(data, name)])) as Record<Column, number[]>

  const n = cols.distance_m.length
  if (n === 0) throw new ChartDataError('empty', 'The comparison has no data points')
  for (const name of REQUIRED) {
    if (cols[name].length !== n) {
      throw new ChartDataError('malformed', `Column "${name}" has ${cols[name].length} rows, expected ${n}`)
    }
  }
  if (n < 2) throw new ChartDataError('empty', 'The comparison needs at least 2 data points to chart')
  for (let i = 1; i < n; i++) {
    if (cols.distance_m[i] <= cols.distance_m[i - 1]) {
      throw new ChartDataError('malformed', `Lap distance does not increase at row ${i + 1}`)
    }
  }

  const percent = (values: number[]) => values.map((v) => v * 100)
  return {
    distance: cols.distance_m,
    speed: { ref: cols.ref_speed_kmh, cmp: cols.cmp_speed_kmh },
    throttle: { ref: percent(cols.ref_throttle), cmp: percent(cols.cmp_throttle) },
    brake: { ref: percent(cols.ref_brake), cmp: percent(cols.cmp_brake) },
    delta: cols.delta_ms.map((ms) => ms / 1000),
  }
}
