/* Shapes returned by the FastAPI backend (see api/services.py). */

export interface LapMeta {
  id: string
  filename: string
  session_uid: string | null
  lap_number: number
  lap_time_ms: number | null
  lap_time: string | null
  valid: boolean
  samples: number
  start_distance_m: number
  end_distance_m: number
}

export interface LapsResponse {
  laps: LapMeta[]
  skipped: Array<{ id: string; error: string }>
}

export interface DeltaPoint {
  distance_m: number
  delta_ms: number
}

export interface ComparisonSummary {
  reference_lap_time_ms: number | null
  comparison_lap_time_ms: number | null
  /** comparison minus reference; positive = comparison slower. null if a lap time is unknown. */
  total_difference_ms: number | null
  final_delta_ms: number
  final_distance_m: number
  largest_loss: DeltaPoint | null
  largest_gain: DeltaPoint | null
  points: number
  start_distance_m: number
  end_distance_m: number
}

export interface CompareResponse {
  id: string
  reference: LapMeta
  comparison: LapMeta
  warnings: string[]
  summary: ComparisonSummary
}

export type EventStatus = 'matched' | 'grouped' | 'ambiguous' | 'ref_only' | 'cmp_only'

export interface DetectedEvent {
  start_m: number
  end_m: number
  min_speed_kmh: number
  min_speed_m: number
  brake_start_m: number | null
  peak_brake: number
  pickup_m: number | null
  full_throttle_m: number | null
}

export interface EventRow {
  name: string
  position_m: number
  status: EventStatus
  note: string
  comparable: boolean
  /** comparison minus reference through the event; positive = comparison lost time. */
  time_delta_ms: number | null
  brake_start_diff_m: number | null
  min_speed_diff_kmh: number | null
  pickup_diff_m: number | null
  full_throttle_diff_m: number | null
  ref: DetectedEvent | null
  cmp: DetectedEvent | null
  ref_events: DetectedEvent[]
  cmp_events: DetectedEvent[]
}

export interface EventsResponse {
  comparison_id: string
  count: number
  events: EventRow[]
}

/** GET /api/comparisons/{id}. `data` holds the aligned columns; it is validated before charting. */
export interface ComparisonDetail {
  id: string
  reference: LapMeta | null
  comparison: LapMeta | null
  summary: Partial<ComparisonSummary>
  data: Record<string, unknown>
}
