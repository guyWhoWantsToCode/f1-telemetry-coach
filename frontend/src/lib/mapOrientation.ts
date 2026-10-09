import type { MapOrientation } from '../api/types'

export interface ChosenOrientation {
  /** Flip Z so that right turns look like right turns (steering-verified). */
  mirrorZ: boolean
  /** True when a recorded lap's steering confirmed the orientation. */
  verified: boolean
  r: number | null
}

/**
 * Which orientation to draw with. Sources are tried in order (the circuit trace, then the
 * reference lap, then the comparison lap): the first one confirmed by steering wins, otherwise the
 * map is drawn unflipped and marked unverified.
 */
export function pickOrientation(...sources: Array<MapOrientation | null | undefined>): ChosenOrientation {
  const present = sources.filter((s): s is MapOrientation => s !== null && s !== undefined)
  const verified = present.find((s) => s.verified)
  if (verified) return { mirrorZ: verified.mirror_z, verified: true, r: verified.r }
  return { mirrorZ: false, verified: false, r: present.find((s) => s.r !== null)?.r ?? null }
}
