import { describe, expect, it } from 'vitest'
import { ChartDataError, toChartData } from './chartData'

function columns(n = 4) {
  const seq = (f: (i: number) => number) => Array.from({ length: n }, (_, i) => f(i))
  return {
    distance_m: seq((i) => i * 5),
    ref_time_ms: seq((i) => i * 100),
    cmp_time_ms: seq((i) => i * 110),
    delta_ms: seq((i) => i * 10),
    ref_speed_kmh: seq((i) => 200 + i),
    cmp_speed_kmh: seq((i) => 190 + i),
    ref_throttle: seq(() => 1),
    cmp_throttle: seq(() => 0.5),
    ref_brake: seq(() => 0),
    cmp_brake: seq(() => 0.25),
  }
}

function failure(raw: unknown): ChartDataError {
  try {
    toChartData(raw)
  } catch (e) {
    expect(e).toBeInstanceOf(ChartDataError)
    return e as ChartDataError
  }
  throw new Error('expected toChartData to throw')
}

describe('toChartData', () => {
  it('keeps every point and passes values through', () => {
    const d = toChartData(columns(201))
    expect(d.distance).toHaveLength(201)
    expect(d.speed.ref[3]).toBe(203)
    expect(d.speed.cmp[3]).toBe(193)
  })

  it('shows throttle and brake as 0-100 %', () => {
    const d = toChartData(columns())
    expect(d.throttle.ref).toEqual([100, 100, 100, 100])
    expect(d.throttle.cmp[0]).toBe(50)
    expect(d.brake.cmp[0]).toBe(25)
  })

  it('converts delta to seconds without changing its sign', () => {
    const raw = columns()
    raw.delta_ms = [-2000, 0, 1500, 5948]
    expect(toChartData(raw).delta).toEqual([-2, 0, 1.5, 5.948])
  })

  it('reports a missing column as malformed', () => {
    const raw: Record<string, unknown> = columns()
    delete raw.ref_speed_kmh
    const e = failure(raw)
    expect(e.kind).toBe('malformed')
    expect(e.message).toContain('ref_speed_kmh')
  })

  it('reports columns of different lengths as malformed', () => {
    const raw = columns()
    raw.cmp_brake = raw.cmp_brake.slice(0, 2)
    expect(failure(raw).message).toContain('cmp_brake')
  })

  it('reports non-numeric and non-finite values as malformed', () => {
    const raw: Record<string, unknown> = columns()
    raw.cmp_speed_kmh = [190, 'fast', 192, 193]
    expect(failure(raw).kind).toBe('malformed')
    raw.cmp_speed_kmh = [190, NaN, 192, 193]
    expect(failure(raw).kind).toBe('malformed')
  })

  it('reports non-increasing distance as malformed', () => {
    const raw = columns()
    raw.distance_m = [0, 5, 5, 10]
    expect(failure(raw).message).toContain('row 3')
  })

  it('reports no data as empty, not malformed', () => {
    expect(failure(columns(0)).kind).toBe('empty')
    expect(failure(columns(1)).kind).toBe('empty')
  })

  it('rejects non-object input', () => {
    expect(failure(null).kind).toBe('malformed')
    expect(failure([1, 2]).kind).toBe('malformed')
  })
})
