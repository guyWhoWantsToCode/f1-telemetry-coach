/* Display formatting only. All telemetry numbers come from the API already computed. */
import type { Tone } from '../design'

const MINUS = '−'
const DASH = '—'

function signed(value: number, digits: number): string {
  const text = Math.abs(value).toFixed(digits)
  if (Number(text) === 0) return text
  return `${value < 0 ? MINUS : '+'}${text}`
}

/** "+5.948 s" / "-2.008 s". */
export const fmtSeconds = (ms: number, digits = 3) => `${signed(ms / 1000, digits)} s`

/** Signed number with unit, e.g. "+10 m". null -> em dash. */
export const fmtSigned = (value: number | null, unit: string, digits = 0) =>
  value === null ? DASH : `${signed(value, digits)} ${unit}`

export const fmtMeters = (m: number) => `${Math.round(m)} m`

/** Time delta -> semantic tone: positive (slower / time lost) is loss, negative is gain. */
export function deltaTone(ms: number | null): Tone {
  if (ms === null || Math.abs(ms) < 0.5) return 'neutral'
  return ms > 0 ? 'loss' : 'gain'
}

export const shortSession = (uid: string | null) => (uid ? uid.slice(0, 8) : DASH)

export const EM_DASH = DASH
