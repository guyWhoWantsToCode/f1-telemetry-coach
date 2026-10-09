/* The only place that talks to the backend. Components call these functions, never fetch(). */
import type {
  CatalogTrack,
  CompareResponse,
  ComparisonDetail,
  EventsResponse,
  LapMeta,
  LapPathResponse,
  LapsResponse,
  RecordingStatus,
  TrackMapResponse,
  TracksResponse,
} from './types'

export const API_BASE: string = import.meta.env.VITE_API_URL ?? 'http://127.0.0.1:8000'

export class ApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

async function detailOf(res: Response): Promise<string> {
  try {
    const body = await res.json()
    const detail = body?.detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail)) return detail.map((d) => d?.msg ?? JSON.stringify(d)).join('; ')
  } catch {
    // not JSON; fall through
  }
  return `${res.status} ${res.statusText}`.trim()
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let res: Response
  try {
    res = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: { Accept: 'application/json', ...(init.body ? { 'Content-Type': 'application/json' } : {}) },
    })
  } catch (e) {
    if (e instanceof DOMException && e.name === 'AbortError') throw e
    throw new ApiError(0, `Cannot reach the API at ${API_BASE}. Is FastAPI running?`)
  }
  if (!res.ok) throw new ApiError(res.status, await detailOf(res))
  return (await res.json()) as T
}

export function errorMessage(e: unknown): string {
  return e instanceof Error ? e.message : String(e)
}

export const getLaps = (signal?: AbortSignal) => request<LapsResponse>('/api/laps', { signal })

export const compareLaps = (
  referenceId: string,
  comparisonId: string,
  allowInvalid: boolean,
  signal?: AbortSignal,
) =>
  request<CompareResponse>('/api/compare', {
    method: 'POST',
    body: JSON.stringify({ reference_id: referenceId, comparison_id: comparisonId, allow_invalid: allowInvalid }),
    signal,
  })

export const getEvents = (comparisonId: string, signal?: AbortSignal) =>
  request<EventsResponse>(`/api/comparisons/${encodeURIComponent(comparisonId)}/events`, { signal })

export const getComparison = (comparisonId: string, signal?: AbortSignal) =>
  request<ComparisonDetail>(`/api/comparisons/${encodeURIComponent(comparisonId)}`, { signal })

export const getRecordingStatus = (signal?: AbortSignal) =>
  request<RecordingStatus>('/api/recording/status', { signal })

export const startRecording = () => request<RecordingStatus>('/api/recording/start', { method: 'POST' })

export const stopRecording = () => request<RecordingStatus>('/api/recording/stop', { method: 'POST' })

export const getTracks = (signal?: AbortSignal) => request<TracksResponse>('/api/tracks', { signal })

export const getTrackCatalog = (signal?: AbortSignal) =>
  request<{ tracks: CatalogTrack[] }>('/api/catalog/tracks', { signal })

/** Manually assign a lap with no known circuit. Persisted by the backend; the telemetry is not changed. */
export const assignLapTrack = (lapId: string, trackId: number) =>
  request<Pick<LapMeta, 'track_id' | 'track_name' | 'track_source'>>(
    `/api/laps/${encodeURIComponent(lapId)}/track`,
    { method: 'POST', body: JSON.stringify({ track_id: trackId }) },
  )

export const getTrackMap = (trackId: number, signal?: AbortSignal) =>
  request<TrackMapResponse>(`/api/tracks/${trackId}/map`, { signal })

export const getLapPath = (lapId: string, signal?: AbortSignal) =>
  request<LapPathResponse>(`/api/laps/${encodeURIComponent(lapId)}/path`, { signal })
