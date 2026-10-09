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
  /** F1 track ID, or null for laps recorded before track identity existed. */
  track_id: number | null
  track_name: string | null
  /** "telemetry" (reported by the game) or "manual" (assigned by the user). */
  track_source: 'telemetry' | 'manual' | null
  /** Whether world positions (Motion packets) were recorded with this lap. */
  has_positions: boolean
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

export type CornerStatus = 'single' | 'complex' | 'uncertain' | 'unknown' | 'unavailable'

export interface EventRow {
  name: string
  /** The generic event number (the N in "Event N"). */
  event_number: number
  /** Real corner label such as "T11" or "T3-T6"; null unless the mapping is confident. */
  corner_label: string | null
  corner_status: CornerStatus
  corner_confidence: number | null
  corner_numbers: number[]
  corner_candidates: string[]
  corner_reason: string
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
  track: {
    track_id: number | null
    track_name: string | null
    has_corner_metadata: boolean
    has_corner_distances: boolean
    reason: string | null
  }
  events: EventRow[]
}

/** One circuit with a saved profile (GET /api/tracks). */
export interface TrackSummary {
  track_id: number
  name: string
  circuit_name: string | null
  /** false for track IDs the application has no catalog entry for. */
  known: boolean
  track_length_m: number | null
  game_year: number | null
  has_corner_metadata: boolean
  has_corner_distances: boolean
  corner_count: number
  stats: {
    sessions: number
    valid_laps: number
    pb: { lap_id: string; lap_time_ms: number; lap_time: string } | null
  }
  is_active: boolean
  /** Whether a circuit trace has been built from recorded positions. */
  has_map: boolean
}

export interface TracksResponse {
  tracks: TrackSummary[]
  active_track_id: number | null
  /** Laps with no known circuit (recorded before track identity existed). */
  unassigned_laps: number
}

/** A circuit a lap can be assigned to (GET /api/catalog/tracks). */
export interface CatalogTrack {
  track_id: number
  name: string
  circuit_name: string | null
  known: boolean
  has_corner_metadata: boolean
}

/** GET /api/comparisons/{id}. `data` holds the aligned columns; it is validated before charting. */
export interface ComparisonDetail {
  id: string
  reference: LapMeta | null
  comparison: LapMeta | null
  summary: Partial<ComparisonSummary>
  data: Record<string, unknown>
}

export type RecordingState = 'idle' | 'waiting' | 'recording' | 'error'

/** GET/POST /api/recording/* (see api/recording.py). */
export interface RecordingStatus {
  state: RecordingState
  running: boolean
  receiving: boolean
  packets_per_second: number
  packets_total: number
  session_uid: string | null
  current_lap: number | null
  laps_saved: number
  saved_laps: string[]
  unmatched_samples: number
  /** Motion packets decoded so far; 0 while recording means no positions are being captured. */
  motion_packets: number
  parse_errors: number
  last_error: string | null
  port: number
  started_at: number | null
  /** The circuit the game reports right now, from live Session packets. Never set by the UI. */
  active_track_id: number | null
  active_track_name: string | null
  active_track_known: boolean | null
  track_length_m: number | null
  session_type: number | null
  session_type_name: string | null
  track_error: string | null
}

/** How the X/Z plane is drawn so that right turns look like right turns (decided from steering). */
export interface MapOrientation {
  mirror_z: boolean
  /** Correlation of steering with turning; null when there was no steering to check. */
  r: number | null
  verified: boolean
  laps_checked: number
}

export interface MapAxes {
  spans_m: { x: number; y: number; z: number }
  vertical_axis: 'x' | 'y' | 'z'
  vertical_axis_verified: boolean
}

/** A path in world coordinates (metres), indexed by lap distance. */
export interface WorldPath {
  step_m?: number
  distance_m: number[]
  x: number[]
  y: number[]
  z: number[]
}

/** GET /api/tracks/{id}/map: the driver's path for a circuit (never a track centerline). */
export interface TrackMapResponse {
  track_id: number
  available: boolean
  reason: string | null
  message: string | null
  kind?: 'driver_path'
  driver_path: WorldPath | null
  centerline: { available: boolean; reason?: string }
  laps: string[]
  rejected: Array<{ lap_id: string; reason: string }>
  quality?: {
    lap_count: number
    cross_checked: boolean
    spread_m: number
    max_spread_m: number
    closure_gap_m: number
    closed: boolean
    path_length_m: number
    length_ratio: number | null
  }
  axes?: MapAxes
  orientation?: MapOrientation
}

/** GET /api/laps/{id}/path: one lap's own recorded racing line, or why it has none. */
export type LapPathResponse =
  | { lap_id: string; track_id: number | null; available: false; reason: string; message: string }
  | ({ lap_id: string; track_id: number | null; available: true; point_count: number; axes: MapAxes; orientation: MapOrientation } & WorldPath)
