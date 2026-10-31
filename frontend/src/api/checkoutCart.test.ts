import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiClient } from './client'
import { readCheckoutCart } from './checkoutCart'

const cart = {
  id: 'cart',
  user_id: 'buyer',
  store_id: 'store',
  version: 2,
  items: [
    {
      product_id: 'A',
      quantity: 2,
      name: 'synthetic A',
      unit_price_cents: 100,
      available: 9,
      active: true,
    },
  ],
}
function client(consumption: string | null, proposalStatus = 200, cartStatus = 200) {
  const calls: { path: string; method: string }[] = []
  const fetcher = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
    const path = String(url)
    calls.push({ path, method: init?.method ?? 'GET' })
    if (path.endsWith('/cart')) return new Response(JSON.stringify(cart), { status: cartStatus })
    return new Response(
      JSON.stringify({
        action_type: 'CHECKOUT',
        result: consumption ? { cart_consumption: consumption } : { status: 'PENDING_PAYMENT' },
      }),
      { status: proposalStatus },
    )
  })
  vi.stubGlobal('fetch', fetcher)
  return { client: new ApiClient('synthetic-test-token'), calls }
}
afterEach(() => vi.unstubAllGlobals())
describe('checkout server cart reconciliation', () => {
  it.each(['CONSUMED', 'SKIPPED_CART_CHANGED', 'NOT_APPLICABLE'] as const)(
    'reads real cart without replacing it from %s receipt',
    async (consumption) => {
      const api = client(consumption)
      const result = await readCheckoutCart(api.client, 'proposal')
      expect(result.cart).toEqual(cart)
      expect(result.consumption).toBe(consumption)
      expect(result.error).toBeNull()
      expect(api.calls).toEqual([
        { path: '/api/v1/proposals/proposal', method: 'GET' },
        { path: '/api/v1/cart', method: 'GET' },
      ])
    },
  )
  it('legacy receipt does not claim that the cart was consumed', async () => {
    const api = client(null)
    const result = await readCheckoutCart(api.client, 'legacy')
    expect(result.cart).toEqual(cart)
    expect(result.consumption).toBeNull()
  })
  it('receipt query failure still reads the authenticated cart', async () => {
    const api = client('CONSUMED', 403)
    const result = await readCheckoutCart(api.client, 'forbidden')
    expect(result.cart).toEqual(cart)
    expect(result.consumption).toBeNull()
    expect(result.error?.status).toBe(403)
  })
  it('failed cart query remains unknown instead of inventing an empty cart', async () => {
    const api = client('CONSUMED', 200, 503)
    const result = await readCheckoutCart(api.client, 'proposal')
    expect(result.cart).toBeNull()
    expect(result.error?.status).toBe(503)
    expect(api.calls.every((call) => call.method === 'GET')).toBe(true)
  })
})
