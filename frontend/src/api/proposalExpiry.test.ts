import { describe, it, expect, vi } from 'vitest'
import { proposalRemaining, expiryLabel } from './proposalExpiry'

describe('server anchored proposal expiry', () => {
  const start = '2026-11-01T11:32:48Z'
  const end = '2026-11-01T11:37:48Z'
  it('counts down from server time and monotonic elapsed, independent of browser wall clock', () => {
    vi.spyOn(Date, 'now').mockReturnValue(Date.parse('2099-01-01T00:00:00Z'))
    expect(proposalRemaining(end, start, 0)).toBe(300)
    expect(proposalRemaining(end, start, 120001)).toBe(180)
    vi.restoreAllMocks()
  })
  it('clamps at zero and never extends a snapshot', () => {
    expect(proposalRemaining(end, start, 300000)).toBe(0)
    expect(proposalRemaining(end, start, 999999)).toBe(0)
    expect(proposalRemaining(start, end, 0)).toBe(0)
  })
  it('keeps missing or malformed server clock UNKNOWN', () => {
    for (const clock of [undefined, null, 'oops', '2026-11-01T11:32:48'])
      expect(proposalRemaining(end, clock, 0)).toBeNull()
    expect(proposalRemaining('oops', start, 0)).toBeNull()
    expect(proposalRemaining(end, start, -1)).toBeNull()
  })
  it('renders an estimate separately from server expiry authorization', () => {
    expect(expiryLabel(125)).toBe('02:05')
    expect(expiryLabel(0)).toBe('00:00')
    expect(expiryLabel(null)).toBe('UNKNOWN')
  })
})
