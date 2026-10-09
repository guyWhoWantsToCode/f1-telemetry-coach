import { describe, expect, it } from 'vitest'
import {
  boundsOf, fitView, nearestOnPath, panBy, planeToScreen, pointAtDistance, polylinePoints, screenToPlane, toPlane, zoomAt,
  type PathXZ,
} from './mapGeometry'

// A 400 m x 100 m rectangle driven clockwise (X right, Z down), 100 m between points.
const rect: PathXZ = {
  distance_m: [0, 100, 200, 300, 400, 500, 600, 700, 800],
  x: [0, 100, 200, 300, 400, 400, 300, 200, 100],
  z: [0, 0, 0, 0, 0, 100, 100, 100, 100],
}
const SIZE = { width: 800, height: 400 }

describe('map geometry', () => {
  it('fits the circuit with one uniform scale, so proportions are never stretched', () => {
    const view = fitView(boundsOf([rect], false)!, SIZE, 20)
    // 400 m x 100 m in 760 x 360 px: width limits the scale.
    expect(view.scale).toBeCloseTo(760 / 400)
    const [x0, y0] = planeToScreen(0, 0, view, SIZE)
    const [x1, y1] = planeToScreen(400, 100, view, SIZE)
    expect((x1 - x0) / (y1 - y0)).toBeCloseTo(400 / 100) // the aspect ratio of the circuit itself
  })

  it('fits a tall circuit by height instead', () => {
    const tall: PathXZ = { distance_m: [0, 1], x: [0, 100], z: [0, 800] }
    expect(fitView(boundsOf([tall], false)!, SIZE, 20).scale).toBeCloseTo(360 / 800)
  })

  it('keeps the whole circuit inside the viewport after fitting', () => {
    const view = fitView(boundsOf([rect], false)!, SIZE, 16)
    for (let i = 0; i < rect.x.length; i++) {
      const [sx, sy] = planeToScreen(...toPlane(rect.x[i], rect.z[i], false), view, SIZE)
      expect(sx).toBeGreaterThanOrEqual(16 - 1e-6)
      expect(sx).toBeLessThanOrEqual(SIZE.width - 16 + 1e-6)
      expect(sy).toBeGreaterThanOrEqual(16 - 1e-6)
      expect(sy).toBeLessThanOrEqual(SIZE.height - 16 + 1e-6)
    }
  })

  it('mirroring flips Z only: X order and distances are unchanged', () => {
    const plain = boundsOf([rect], false)!
    const mirrored = boundsOf([rect], true)!
    expect(mirrored.minU).toBe(plain.minU)
    expect(mirrored.maxU).toBe(plain.maxU)
    expect([mirrored.minV, mirrored.maxV]).toEqual([-plain.maxV, -plain.minV])
    expect(toPlane(5, 7, true)).toEqual([5, -7])
    expect(toPlane(5, 7, false)).toEqual([5, 7])
  })

  it('has no bounds for an empty path', () => {
    expect(boundsOf([{ distance_m: [], x: [], z: [] }], false)).toBeNull()
  })

  it('screen and plane positions convert back and forth', () => {
    const view = { cu: 50, cv: -20, scale: 3 }
    const [sx, sy] = planeToScreen(70, -5, view, SIZE)
    const [u, v] = screenToPlane(sx, sy, view, SIZE)
    expect(u).toBeCloseTo(70)
    expect(v).toBeCloseTo(-5)
  })

  it('zooming keeps the point under the pointer where it is', () => {
    const fit = fitView(boundsOf([rect], false)!, SIZE)
    const before = screenToPlane(250, 130, fit, SIZE)
    const zoomed = zoomAt(fit, 250, 130, 4, SIZE, fit)
    expect(zoomed.scale).toBeCloseTo(fit.scale * 4)
    const after = screenToPlane(250, 130, zoomed, SIZE)
    expect(after[0]).toBeCloseTo(before[0])
    expect(after[1]).toBeCloseTo(before[1])
  })

  it('limits how far the view can zoom out and in', () => {
    const fit = fitView(boundsOf([rect], false)!, SIZE)
    expect(zoomAt(fit, 0, 0, 0.0001, SIZE, fit).scale).toBeCloseTo(fit.scale * 0.5)
    expect(zoomAt(fit, 0, 0, 1e9, SIZE, fit).scale).toBeCloseTo(fit.scale * 60)
  })

  it('panning moves the circuit with the pointer', () => {
    const fit = fitView(boundsOf([rect], false)!, SIZE)
    const panned = panBy(fit, 40, -25)
    const [x0, y0] = planeToScreen(100, 0, fit, SIZE)
    const [x1, y1] = planeToScreen(100, 0, panned, SIZE)
    expect(x1 - x0).toBeCloseTo(40)
    expect(y1 - y0).toBeCloseTo(-25)
  })

  it('finds a position by lap distance, interpolating but never extrapolating', () => {
    expect(pointAtDistance(rect, 50)).toEqual({ x: 50, z: 0 })
    expect(pointAtDistance(rect, 450)).toEqual({ x: 400, z: 50 })
    expect(pointAtDistance(rect, 800)).toEqual({ x: 100, z: 100 })
    expect(pointAtDistance(rect, -1)).toBeNull()
    expect(pointAtDistance(rect, 801)).toBeNull()
    expect(pointAtDistance({ distance_m: [], x: [], z: [] }, 0)).toBeNull()
  })

  it('finds the lap distance of the point nearest a click', () => {
    expect(nearestOnPath(rect, 210, 8, false)).toEqual({ distance: 200, gap: Math.hypot(10, 8) })
    expect(nearestOnPath(rect, 390, 95, false)?.distance).toBe(500)
    // With a mirrored plane the same click position is a different place on the circuit.
    expect(nearestOnPath(rect, 200, -100, true)?.distance).toBe(700)
    expect(nearestOnPath({ distance_m: [], x: [], z: [] }, 0, 0, false)).toBeNull()
  })

  it('writes a polyline in screen pixels', () => {
    const points = polylinePoints({ distance_m: [0, 1], x: [0, 10], z: [0, 0] }, { cu: 0, cv: 0, scale: 2 }, { width: 100, height: 100 }, false)
    expect(points).toBe('50.0,50.0 70.0,50.0')
  })
})
