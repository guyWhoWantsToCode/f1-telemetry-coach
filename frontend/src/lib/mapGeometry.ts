/*
 * Pure geometry for the track map. World coordinates are metres in the game's X/Z plane (Y is the
 * vertical axis, checked by the backend). The map is drawn in a "plane" (u, v) = (x, ±z): the sign of z
 * is decided by the backend from the driver's steering, so right turns look like right turns. Scale is
 * uniform, so the circuit's proportions are never stretched.
 */

export interface PathXZ {
  distance_m: number[]
  x: number[]
  z: number[]
}

export interface Bounds {
  minU: number
  maxU: number
  minV: number
  maxV: number
}

/** The visible part of the plane: (cu, cv) is at the centre of the viewport, `scale` is pixels per metre. */
export interface View {
  cu: number
  cv: number
  scale: number
}

export interface Size {
  width: number
  height: number
}

export const MIN_ZOOM = 0.5 // relative to the fitted view
export const MAX_ZOOM = 60

/** World X/Z to the drawing plane. `mirrorZ` flips Z (decided from steering by the backend). */
export const toPlane = (x: number, z: number, mirrorZ: boolean): [number, number] => [x, mirrorZ ? -z : z]

export function boundsOf(paths: PathXZ[], mirrorZ: boolean): Bounds | null {
  let minU = Infinity, maxU = -Infinity, minV = Infinity, maxV = -Infinity
  for (const path of paths) {
    for (let i = 0; i < path.x.length; i++) {
      const [u, v] = toPlane(path.x[i], path.z[i], mirrorZ)
      if (u < minU) minU = u
      if (u > maxU) maxU = u
      if (v < minV) minV = v
      if (v > maxV) maxV = v
    }
  }
  return Number.isFinite(minU) ? { minU, maxU, minV, maxV } : null
}

/** The view that shows all of `bounds` with `padding` pixels around it, at one uniform scale. */
export function fitView(bounds: Bounds, size: Size, padding = 16): View {
  const spanU = Math.max(bounds.maxU - bounds.minU, 1e-6)
  const spanV = Math.max(bounds.maxV - bounds.minV, 1e-6)
  const scale = Math.min((size.width - 2 * padding) / spanU, (size.height - 2 * padding) / spanV)
  return { cu: (bounds.minU + bounds.maxU) / 2, cv: (bounds.minV + bounds.maxV) / 2, scale: Math.max(scale, 1e-6) }
}

export const planeToScreen = (u: number, v: number, view: View, size: Size): [number, number] => [
  size.width / 2 + (u - view.cu) * view.scale,
  size.height / 2 + (v - view.cv) * view.scale,
]

export const screenToPlane = (sx: number, sy: number, view: View, size: Size): [number, number] => [
  view.cu + (sx - size.width / 2) / view.scale,
  view.cv + (sy - size.height / 2) / view.scale,
]

/** Zoom by `factor` keeping the plane point under the screen position (sx, sy) where it is. */
export function zoomAt(view: View, sx: number, sy: number, factor: number, size: Size, fit: View): View {
  const scale = Math.min(Math.max(view.scale * factor, fit.scale * MIN_ZOOM), fit.scale * MAX_ZOOM)
  const [u, v] = screenToPlane(sx, sy, view, size)
  return { scale, cu: u - (sx - size.width / 2) / scale, cv: v - (sy - size.height / 2) / scale }
}

/** Drag the view by (dx, dy) screen pixels. */
export const panBy = (view: View, dx: number, dy: number): View => ({
  ...view, cu: view.cu - dx / view.scale, cv: view.cv - dy / view.scale,
})

/** Position at a lap distance by linear interpolation; null outside the recorded range (no extrapolation). */
export function pointAtDistance(path: PathXZ, d: number): { x: number; z: number } | null {
  const ds = path.distance_m
  if (ds.length === 0 || d < ds[0] || d > ds[ds.length - 1]) return null
  let lo = 0
  let hi = ds.length - 1
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1
    if (ds[mid] <= d) lo = mid
    else hi = mid
  }
  const span = ds[hi] - ds[lo]
  const t = span > 0 ? (d - ds[lo]) / span : 0
  return { x: path.x[lo] + (path.x[hi] - path.x[lo]) * t, z: path.z[lo] + (path.z[hi] - path.z[lo]) * t }
}

/** The recorded point closest to the plane position (u, v): its lap distance and how far away it is. */
export function nearestOnPath(path: PathXZ, u: number, v: number, mirrorZ: boolean): { distance: number; gap: number } | null {
  let best = -1
  let bestGap = Infinity
  for (let i = 0; i < path.x.length; i++) {
    const [pu, pv] = toPlane(path.x[i], path.z[i], mirrorZ)
    const gap = Math.hypot(pu - u, pv - v)
    if (gap < bestGap) {
      bestGap = gap
      best = i
    }
  }
  return best < 0 ? null : { distance: path.distance_m[best], gap: bestGap }
}

/** SVG `points` attribute for a path in the current view. */
export function polylinePoints(path: PathXZ, view: View, size: Size, mirrorZ: boolean): string {
  const out: string[] = []
  for (let i = 0; i < path.x.length; i++) {
    const [u, v] = toPlane(path.x[i], path.z[i], mirrorZ)
    const [sx, sy] = planeToScreen(u, v, view, size)
    out.push(`${sx.toFixed(1)},${sy.toFixed(1)}`)
  }
  return out.join(' ')
}
