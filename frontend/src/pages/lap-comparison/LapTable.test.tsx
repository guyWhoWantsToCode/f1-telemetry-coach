// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { CATALOG, makeLap } from '../../lib/testData'
import { LapTable } from './LapTable'

afterEach(cleanup)

const legacy = makeLap({ id: 'old_lap03', lap_number: 3, track_id: null, track_name: null, track_source: null })

describe('LapTable', () => {
  const base = { refId: null, cmpId: null, onSelectRef: vi.fn(), onSelectCmp: vi.fn() }

  it('has no assignment controls for laps with a known circuit', () => {
    render(<LapTable {...base} laps={[makeLap()]} />)
    expect(screen.queryByText('Assign track')).toBeNull()
  })

  it('assigns a legacy lap only after a circuit is chosen and Assign is pressed', () => {
    const onAssign = vi.fn()
    render(<LapTable {...base} laps={[legacy]} assign={{ catalog: CATALOG, onAssign }} />)
    const assign = screen.getByRole('button', { name: 'Assign lap 3' }) as HTMLButtonElement
    expect(assign.disabled).toBe(true) // nothing is assigned by default
    fireEvent.change(screen.getByLabelText('Circuit for lap 3'), { target: { value: '15' } })
    expect(onAssign).not.toHaveBeenCalled() // choosing alone does nothing
    expect(assign.disabled).toBe(false)
    fireEvent.click(assign)
    expect(onAssign).toHaveBeenCalledTimes(1)
    expect(onAssign).toHaveBeenCalledWith('old_lap03', 15)
  })

  it('the circuit picker lists the whole catalog with friendly names', () => {
    render(<LapTable {...base} laps={[legacy]} assign={{ catalog: CATALOG, onAssign: vi.fn() }} />)
    const select = screen.getByLabelText('Circuit for lap 3') as HTMLSelectElement
    expect([...select.options].map((o) => o.text)).toEqual(['Circuit...', 'Monza', 'Suzuka', 'Circuit of the Americas'])
  })

  it('still lets the lap be chosen as reference or comparison', () => {
    const onSelectRef = vi.fn()
    render(<LapTable {...base} onSelectRef={onSelectRef} laps={[legacy]} assign={{ catalog: CATALOG, onAssign: vi.fn() }} />)
    fireEvent.click(screen.getByRole('button', { name: 'Use lap 3 as reference' }))
    expect(onSelectRef).toHaveBeenCalledWith('old_lap03')
  })
})
