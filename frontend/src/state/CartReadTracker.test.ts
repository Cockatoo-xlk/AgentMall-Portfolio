import { describe, expect, it } from 'vitest'
import { CartReadTracker } from './CartReadTracker'
const v2 = { id: 'cart', version: 2 }
const v3 = { id: 'cart', version: 3 }
describe('cart read ordering and independent version watermark', () => {
  it('rejects an older response after a newer successful read', () => {
    const gate = new CartReadTracker()
    const old = gate.begin(),
      current = gate.begin()
    expect(gate.accept(current, v3)).toBe(true)
    expect(gate.accept(old, v2)).toBe(false)
  })
  it('a latest failed read invalidates old replies without losing known version', () => {
    const gate = new CartReadTracker()
    expect(gate.accept(gate.begin(), v3)).toBe(true)
    const old = gate.begin(),
      failed = gate.begin()
    expect(gate.fail(failed)).toBe(true)
    expect(gate.accept(old, v2)).toBe(false)
    expect(gate.accept(gate.begin(), v2)).toBe(false)
    expect(gate.accept(gate.begin(), v3)).toBe(true)
  })
  it('a write response invalidates earlier reads and advances the watermark', () => {
    const gate = new CartReadTracker()
    const old = gate.begin()
    expect(gate.acceptWrite(v3)).toBe(true)
    expect(gate.accept(old, v2)).toBe(false)
    expect(gate.acceptWrite(v2)).toBe(false)
  })
  it('identity reset rejects previous session reads and allows its new cart', () => {
    const gate = new CartReadTracker()
    const old = gate.begin()
    gate.accept(old, v3)
    gate.reset()
    expect(gate.accept(old, { id: 'cart', version: 9 })).toBe(false)
    expect(gate.accept(gate.begin(), { id: 'other-cart', version: 0 })).toBe(true)
  })
})
