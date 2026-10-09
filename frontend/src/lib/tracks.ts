/* Pure helpers for the circuit selector. No telemetry logic: only which circuit to view and how to
   label it. The live (active) circuit comes from the backend and is never set from here. */
import type { LapMeta, TracksResponse, TrackSummary } from '../api/types'

/** What the track selector is viewing: a circuit's track ID, or the laps with no known circuit. */
export const UNASSIGNED = 'unassigned' as const

export type Viewing = number | typeof UNASSIGNED

/** Laps belonging to the circuit being viewed ('unassigned' = laps with no track). */
export function lapsFor(laps: LapMeta[], viewing: Viewing | null): LapMeta[] {
  if (viewing === null) return []
  return laps.filter((l) => (viewing === UNASSIGNED ? l.track_id === null : l.track_id === viewing))
}

/**
 * The circuit to view when none has been picked: the live circuit if it has a profile, else the
 * circuit with the most valid laps, else the unassigned laps (e.g. only legacy laps exist).
 */
export function chooseViewing(data: TracksResponse | null): Viewing | null {
  if (data === null) return null
  const { tracks, active_track_id: active } = data
  if (active !== null && tracks.some((t) => t.track_id === active)) return active
  if (tracks.length > 0) {
    return [...tracks].sort((a, b) => b.stats.valid_laps - a.stats.valid_laps)[0].track_id
  }
  return data.unassigned_laps > 0 ? UNASSIGNED : null
}

/** Whether the selection still points at something that exists. */
export function isViewable(data: TracksResponse, viewing: Viewing): boolean {
  return viewing === UNASSIGNED ? data.unassigned_laps > 0 : data.tracks.some((t) => t.track_id === viewing)
}

export interface TrackOption {
  value: string
  label: string
}

/** Selector options: every circuit with a saved profile, then the unassigned laps if there are any. */
export function trackOptions(data: TracksResponse): TrackOption[] {
  const options = data.tracks.map((t) => ({
    value: String(t.track_id),
    label: data.active_track_id === t.track_id ? `${t.name} (live)` : t.name,
  }))
  if (data.unassigned_laps > 0) {
    options.push({ value: UNASSIGNED, label: `Unassigned laps (${data.unassigned_laps})` })
  }
  return options
}

export const parseViewing = (value: string): Viewing => (value === UNASSIGNED ? UNASSIGNED : Number(value))

export function findTrack(data: TracksResponse | null, viewing: Viewing | null): TrackSummary | undefined {
  return viewing === null || viewing === UNASSIGNED ? undefined : data?.tracks.find((t) => t.track_id === viewing)
}

/** Name of an assignable circuit for the picker (the circuit name when known, else the game's label). */
export const catalogLabel = (t: { name: string; circuit_name: string | null }) => t.circuit_name ?? t.name
