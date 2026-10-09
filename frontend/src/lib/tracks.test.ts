import { describe, expect, it } from 'vitest'
import { chooseViewing, isViewable, lapsFor, parseViewing, trackOptions, UNASSIGNED } from './tracks'
import { makeLap, makeTracks } from './testData'

describe('track selector logic', () => {
  it('lists every circuit that has a saved profile, in the order given', () => {
    const options = trackOptions(makeTracks())
    expect(options.map((o) => o.label)).toEqual(['Circuit of the Americas', 'Monza', 'Suzuka'])
    expect(options.map((o) => o.value)).toEqual(['15', '11', '13'])
  })

  it('marks only the live circuit as live, and adds unassigned laps when there are some', () => {
    const options = trackOptions(makeTracks({ active_track_id: 11, unassigned_laps: 3 }))
    expect(options.map((o) => o.label)).toEqual([
      'Circuit of the Americas', 'Monza (live)', 'Suzuka', 'Unassigned laps (3)',
    ])
    expect(options.at(-1)?.value).toBe(UNASSIGNED)
  })

  it('parses selector values back to a track ID or the unassigned bucket', () => {
    expect(parseViewing('15')).toBe(15)
    expect(parseViewing('unassigned')).toBe(UNASSIGNED)
  })

  it('shows only the laps of the circuit being viewed', () => {
    const laps = [
      makeLap({ id: 'a', track_id: 15 }),
      makeLap({ id: 'b', track_id: 11 }),
      makeLap({ id: 'c', track_id: null, track_name: null, track_source: null }),
    ]
    expect(lapsFor(laps, 15).map((l) => l.id)).toEqual(['a'])
    expect(lapsFor(laps, 11).map((l) => l.id)).toEqual(['b'])
    expect(lapsFor(laps, UNASSIGNED).map((l) => l.id)).toEqual(['c'])
    expect(lapsFor(laps, null)).toEqual([])
  })

  describe('chooseViewing', () => {
    it('prefers the live circuit when it has a profile', () => {
      expect(chooseViewing(makeTracks({ active_track_id: 13 }))).toBe(13)
    })

    it('without a live circuit picks the circuit with the most valid laps', () => {
      expect(chooseViewing(makeTracks())).toBe(11) // Monza has 5 valid laps
    })

    it('ignores a live circuit that has no profile yet', () => {
      expect(chooseViewing(makeTracks({ active_track_id: 31 }))).toBe(11)
    })

    it('falls back to unassigned laps, then to nothing', () => {
      expect(chooseViewing(makeTracks({ tracks: [], unassigned_laps: 4 }))).toBe(UNASSIGNED)
      expect(chooseViewing(makeTracks({ tracks: [], unassigned_laps: 0 }))).toBeNull()
      expect(chooseViewing(null)).toBeNull()
    })
  })

  it('knows whether a selection still exists', () => {
    const data = makeTracks({ unassigned_laps: 0 })
    expect(isViewable(data, 15)).toBe(true)
    expect(isViewable(data, 99)).toBe(false)
    expect(isViewable(data, UNASSIGNED)).toBe(false)
    expect(isViewable({ ...data, unassigned_laps: 2 }, UNASSIGNED)).toBe(true)
  })
})
