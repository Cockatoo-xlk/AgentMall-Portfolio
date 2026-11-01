import { afterEach, it, expect, vi } from 'vitest'
import { ApiClient } from './client'
afterEach(() => vi.unstubAllGlobals())
it('reads volatile clock from a header without changing proposal payload', async () => {
  const payload = { proposal_id: 'p1', canonical_payload: { items: [] } }
  vi.stubGlobal(
    'fetch',
    vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify(payload), {
          headers: {
            'Content-Type': 'application/json',
            'X-Server-Time': '2026-11-01T11:32:48Z',
          },
        }),
      ),
  )
  expect(await new ApiClient().get('/proposals/p1')).toEqual({
    ...payload,
    server_time: '2026-11-01T11:32:48Z',
  })
  expect(payload).not.toHaveProperty('server_time')
})
it('does not attach proposal clock to writes or unrelated resources', async () => {
  vi.stubGlobal(
    'fetch',
    vi
      .fn()
      .mockImplementation(() =>
        Promise.resolve(
          new Response('{"status":"ok"}', {
            headers: { 'X-Server-Time': '2026-11-01T11:32:48Z' },
          }),
        ),
      ),
  )
  expect(await new ApiClient().post('/checkout/proposals', {})).toEqual({ status: 'ok' })
  expect(await new ApiClient().get('/cart')).toEqual({ status: 'ok' })
})
