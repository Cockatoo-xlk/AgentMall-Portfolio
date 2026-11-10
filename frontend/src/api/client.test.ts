import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiClient, ApiError } from './client'
import { confirmAndExecute } from './checkout'
import { parseBudget, money } from './format'

beforeEach(() => vi.restoreAllMocks())
const proposal = {
  proposal_id: 'p1',
  status: 'PENDING',
  expires_at: '2099-01-01T00:00:00Z',
  confirmation: null,
  result: null,
}
function wire(responses: (object | Error)[]) {
  return vi.spyOn(globalThis, 'fetch').mockImplementation(async () => {
    const r = responses.shift()
    if (r instanceof Error) throw r
    return new Response(JSON.stringify(r), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    })
  })
}
describe('API boundary', () => {
  it('sends only in-memory bearer and never retries ambiguous writes', async () => {
    const fetch = wire([new TypeError('network')])
    const client = new ApiClient('private-token')
    await expect(client.post('/orders', { proposal_id: 'p1' }, 'same-key')).rejects.toMatchObject({
      ambiguous: true,
    })
    expect(fetch).toHaveBeenCalledTimes(1)
    expect(new Headers(fetch.mock.calls[0][1]?.headers).get('Authorization')).toBe(
      'Bearer private-token',
    )
    expect(new Headers(fetch.mock.calls[0][1]?.headers).get('Idempotency-Key')).toBe('same-key')
  })
  it('expires auth on 401 without leaking a raw server body', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response('{"code":"UNAUTHORIZED","message":"secret"}', { status: 401 }),
    )
    const expired = vi.fn()
    const client = new ApiClient('token', expired)
    await expect(client.get('/me')).rejects.toBeInstanceOf(ApiError)
    expect(expired).toHaveBeenCalledOnce()
  })
  it('aborts a timed out write and marks its outcome uncertain', async () => {
    vi.useFakeTimers()
    vi.spyOn(globalThis, 'fetch').mockImplementation(
      (_url, options) =>
        new Promise((_resolve, reject) => {
          options?.signal?.addEventListener('abort', () =>
            reject(new DOMException('aborted', 'AbortError')),
          )
        }),
    )
    const pending = new ApiClient(null, undefined, 20).post('/orders', {}).catch((e) => e)
    await vi.advanceTimersByTimeAsync(21)
    expect(await pending).toMatchObject({ ambiguous: true, code: 'NETWORK_ERROR' })
    vi.useRealTimers()
  })
})
describe('checkout reconciliation', () => {
  it('recovers a committed receipt after response loss without another write', async () => {
    const receipt = { order_id: 'o1' }
    const order = { id: 'o1', status: 'PENDING_PAYMENT' }
    const fetch = wire([
      proposal,
      { confirmation_id: 'c1' },
      new TypeError('response lost'),
      { ...proposal, status: 'EXECUTED', result: receipt },
      order,
    ])
    expect(await confirmAndExecute(new ApiClient('token'), 'p1')).toEqual(order)
    expect(fetch.mock.calls.filter(([, o]) => o?.method === 'POST')).toHaveLength(2)
    expect(new Headers(fetch.mock.calls[2][1]?.headers).get('Idempotency-Key')).toBe('web:order:p1')
  })
  it('does not execute again when the proposal already has a receipt', async () => {
    const fetch = wire([
      { ...proposal, status: 'EXECUTED', result: { order_id: 'o1' } },
      { id: 'o1' },
    ])
    expect(await confirmAndExecute(new ApiClient('token'), 'p1')).toMatchObject({ id: 'o1' })
    expect(fetch.mock.calls.every(([, o]) => o?.method === 'GET')).toBe(true)
  })
  it('leaves uncertain confirmation pending instead of automatically executing', async () => {
    const fetch = wire([
      proposal,
      new TypeError('lost'),
      {
        ...proposal,
        status: 'APPROVED',
        confirmation: { confirmation_id: 'c1', decision: 'approve' },
      },
    ])
    await expect(confirmAndExecute(new ApiClient('token'), 'p1')).rejects.toMatchObject({
      code: 'OUTCOME_UNKNOWN',
    })
    expect(fetch.mock.calls.filter(([, o]) => o?.method === 'POST')).toHaveLength(1)
  })
  it('refuses an expired proposal before confirmation', async () => {
    const fetch = wire([{ ...proposal, status: 'EXPIRED' }])
    await expect(confirmAndExecute(new ApiClient('token'), 'p1')).rejects.toMatchObject({
      code: 'STALE_PROPOSAL',
    })
    expect(fetch).toHaveBeenCalledTimes(1)
  })
  it('uses server expiry state even when the browser clock is ahead', async () => {
    vi.spyOn(Date, 'now').mockReturnValue(Date.parse('2100-01-01T00:00:00Z'))
    const fetch = wire([proposal, { confirmation_id: 'c1' }, { order_id: 'o1' }, { id: 'o1' }])
    expect(await confirmAndExecute(new ApiClient('token'), 'p1')).toMatchObject({ id: 'o1' })
    expect(fetch.mock.calls.filter(([, options]) => options?.method === 'POST')).toHaveLength(2)
  })
})
it('parses integer cents without accepting floating-point or exponent input', () => {
  expect(parseBudget('299.99')).toBe(29999)
  expect(parseBudget('300')).toBe(30000)
  expect(parseBudget('')).toBeNull()
  expect(() => parseBudget('1e3')).toThrow()
  expect(() => parseBudget('0.001')).toThrow()
  expect(money(19900)).toBe('¥199.00')
})

describe('event stream', () => {
  it('delivers a complete frame before EOF and reassembles split UTF-8', async () => {
    let body!: ReadableStreamDefaultController<Uint8Array>
    const response = new Response(new ReadableStream<Uint8Array>({
      start(controller) { body = controller },
    }), { headers: { 'Content-Type': 'text/event-stream' } })
    const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValue(response)
    const received = vi.fn()
    const done = new ApiClient('memory-token').stream('/agent/runs/r/events/stream?after_seq=5', received, new AbortController().signal)
    const bytes = new TextEncoder().encode(': heartbeat\n\nid: 6\nevent: run_event\ndata: {"seq":6,"value":"路由"}\n\n')
    const split = bytes.indexOf(232) + 1
    body.enqueue(bytes.slice(0, split))
    body.enqueue(bytes.slice(split))
    await vi.waitFor(() => expect(received).toHaveBeenCalledWith('run_event', '{"seq":6,"value":"路由"}'))
    body.close()
    await done
    expect(fetch.mock.calls[0][0]).toBe('/api/v1/agent/runs/r/events/stream?after_seq=5')
    expect(new Headers(fetch.mock.calls[0][1]?.headers).get('Authorization')).toBe('Bearer memory-token')
  })

  it('ends the authenticated session on 401 or in-stream expiry', async () => {
    const fetch = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(new Response(null, { status: 401 }))
      .mockResolvedValueOnce(new Response('event: auth_expired\ndata: {}\n\n', {
        headers: { 'Content-Type': 'text/event-stream' },
      }))
    const expired = vi.fn()
    const client = new ApiClient('token', expired)
    for (let i = 0; i < 2; i++) {
      await expect(client.stream('/agent/stream', vi.fn(), new AbortController().signal)).rejects.toMatchObject({ status: 401 })
    }
    expect(expired).toHaveBeenCalledTimes(2)
    expect(fetch).toHaveBeenCalledTimes(2)
  })
})

it('posts a merchant question in the body with memory auth and streams read progress without retries', async () => {
  const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('event: progress\ndata: {"phase":"tool"}\n\n', { headers: { 'Content-Type': 'text/event-stream' } }))
  const receive=vi.fn()
  await new ApiClient('merchant-memory-token').stream('/merchant/copilot/analyze/stream', receive, new AbortController().signal, { question: '待发货订单' })
  const [url, options] = fetch.mock.calls[0]
  expect(url).toBe('/api/v1/merchant/copilot/analyze/stream')
  expect(options?.method).toBe('POST')
  expect(options?.body).toBe(JSON.stringify({question:'待发货订单'}))
  expect(new Headers(options?.headers).get('Authorization')).toBe('Bearer merchant-memory-token')
  expect(String(url)).not.toContain('token')
  expect(receive).toHaveBeenCalledWith('progress','{"phase":"tool"}')
  expect(fetch).toHaveBeenCalledOnce()
})
