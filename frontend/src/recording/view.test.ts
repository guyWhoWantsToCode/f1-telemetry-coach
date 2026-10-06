import { describe, expect, it } from 'vitest'
import { makeStatus } from './testStatus'
import { recordingView } from './view'

describe('recordingView', () => {
  it('idle: no packet status, no lap, nothing saved yet', () => {
    const v = recordingView(makeStatus())
    expect(v).toMatchObject({ state: 'idle', label: 'Idle', packets: null, lap: null, saved: null, running: false })
  })

  it('waiting: listening but no packets', () => {
    const v = recordingView(makeStatus({ state: 'waiting', running: true }))
    expect(v).toMatchObject({ label: 'Waiting for packets', packets: 'No packets', lap: null, saved: '0 saved', running: true })
  })

  it('recording: packet rate, current lap and saved count', () => {
    const v = recordingView(makeStatus({
      state: 'recording', running: true, receiving: true, packets_per_second: 611.6, current_lap: 3, laps_saved: 2,
    }))
    expect(v).toMatchObject({ label: 'Recording', packets: 'Receiving 612 pkt/s', lap: 'Lap 3', saved: '2 saved' })
  })

  it('after stopping, keeps showing how many laps were saved', () => {
    const v = recordingView(makeStatus({ laps_saved: 3 }))
    expect(v).toMatchObject({ state: 'idle', saved: '3 saved', packets: null, lap: null })
  })

  it('error: shows the last error', () => {
    const v = recordingView(makeStatus({ state: 'error', last_error: 'cannot listen on UDP port 20777' }))
    expect(v).toMatchObject({ label: 'Error', error: 'cannot listen on UDP port 20777', running: false })
  })

  it('offline and not-yet-loaded states', () => {
    expect(recordingView(null, false)).toMatchObject({ state: 'offline', label: 'API offline' })
    expect(recordingView(null, true)).toMatchObject({ state: 'offline', label: 'Checking' })
    expect(recordingView(makeStatus({ running: true, state: 'recording' }), false).state).toBe('offline')
  })
})
