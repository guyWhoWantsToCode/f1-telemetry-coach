import type { CatalogTrack, EventRow, LapMeta, TracksResponse, TrackSummary } from '../api/types'

/** Fixtures for frontend tests only. */
export function makeLap(overrides: Partial<LapMeta> = {}): LapMeta {
  return {
    id: 'aaaa000000000001_lap01_1m40.000s',
    filename: 'aaaa000000000001_lap01_1m40.000s.csv',
    session_uid: 'aaaa000000000001',
    lap_number: 1,
    lap_time_ms: 100000,
    lap_time: '1:40.000',
    valid: true,
    samples: 800,
    start_distance_m: 2,
    end_distance_m: 5513,
    track_id: 15,
    track_name: 'Circuit of the Americas',
    track_source: 'telemetry',
    has_positions: true,
    ...overrides,
  }
}

export function makeTrack(overrides: Partial<TrackSummary> = {}): TrackSummary {
  return {
    track_id: 15,
    name: 'Circuit of the Americas',
    circuit_name: 'Circuit of the Americas',
    known: true,
    track_length_m: 5513,
    game_year: 2025,
    has_corner_metadata: true,
    has_corner_distances: false,
    corner_count: 20,
    stats: { sessions: 1, valid_laps: 3, pb: { lap_id: 'x', lap_time_ms: 100000, lap_time: '1:40.000' } },
    is_active: false,
    has_map: false,
    ...overrides,
  }
}

/** COTA, Monza and Suzuka, each with a profile; nothing unassigned. */
export function makeTracks(overrides: Partial<TracksResponse> = {}): TracksResponse {
  return {
    tracks: [
      makeTrack(),
      makeTrack({ track_id: 11, name: 'Monza', circuit_name: null, track_length_m: 5793, has_corner_metadata: false,
        corner_count: 0, stats: { sessions: 2, valid_laps: 5, pb: { lap_id: 'm', lap_time_ms: 80000, lap_time: '1:20.000' } } }),
      makeTrack({ track_id: 13, name: 'Suzuka', circuit_name: null, track_length_m: 5807, has_corner_metadata: false,
        corner_count: 0, stats: { sessions: 0, valid_laps: 0, pb: null } }),
    ],
    active_track_id: null,
    unassigned_laps: 0,
    ...overrides,
  }
}

export const CATALOG: CatalogTrack[] = [
  { track_id: 11, name: 'Monza', circuit_name: null, known: true, has_corner_metadata: false },
  { track_id: 13, name: 'Suzuka', circuit_name: null, known: true, has_corner_metadata: false },
  { track_id: 15, name: 'Texas', circuit_name: 'Circuit of the Americas', known: true, has_corner_metadata: true },
]

export function makeEvent(overrides: Partial<EventRow> = {}): EventRow {
  return {
    name: 'Event 4',
    event_number: 4,
    corner_label: null,
    corner_status: 'unavailable',
    corner_confidence: null,
    corner_numbers: [],
    corner_candidates: [],
    corner_reason: '',
    position_m: 1915,
    status: 'matched',
    note: '',
    comparable: true,
    time_delta_ms: 120,
    brake_start_diff_m: 10,
    min_speed_diff_kmh: -2,
    pickup_diff_m: 5,
    full_throttle_diff_m: 15,
    ref: null,
    cmp: null,
    ref_events: [],
    cmp_events: [],
    ...overrides,
  }
}
