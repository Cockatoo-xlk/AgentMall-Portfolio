import { describe, expect, it, vi } from 'vitest'
import { ApiClient, ApiError } from './client'
import {
  createPaymentOperation,
  preparePayment,
  decidePayment,
  readPaymentOutcome,
  storePaymentOperation,
  loadPaymentOperation,
  paymentStorageKey,
} from './payment'
import type { Confirmation, MockPaymentProposal, MockPaymentReceipt, Order } from './types'

const original: Order = {
  id: 'order-1',
  user_id: 'buyer-1',
  store_id: 'store-1',
  proposal_id: 'checkout-1',
  status: 'PENDING_PAYMENT',
  total_cents: 19900,
  currency: 'CNY',
  address_label: 'demo_dorm',
  expires_at: '2099-01-01T00:15:00Z',
  created_at: '2099-01-01T00:00:00Z',
  version: 1,
  policy_version: 'demo-v1',
  items: [],
}
function fixture() {
  const state = {
    order: { ...original },
    proposal: null as MockPaymentProposal | null,
    losePrepare: false,
    loseConfirmation: false,
    loseExecution: false,
    failReads: false,
    decline: false,
    forbidden: false,
  }
  const api = new ApiClient()
  api.request = vi.fn(async (path: string, method: string, body?: unknown, key?: string) => {
    if (state.forbidden) throw new ApiError(403, 'FORBIDDEN')
    if (method === 'GET' && state.failReads) throw new ApiError(0, 'NETWORK_ERROR')
    if (method === 'GET' && path === '/orders/order-1') return structuredClone(state.order)
    if (method === 'GET' && path === '/proposals/payment-1') return structuredClone(state.proposal)
    if (path.endsWith('/payment-proposals')) {
      expect(method).toBe('POST')
      expect(key).toBeTruthy()
      expect(body).toMatchObject({
        expected_version: 1,
        proposal_slot: 'web_payment',
      })
      state.proposal ??= {
        proposal_id: 'payment-1',
        action_type: 'MOCK_PAYMENT',
        payload_hash: 'hash',
        schema_version: 1,
        expires_at: '2099-01-01T00:05:00Z',
        status: 'PENDING',
        confirmation: null,
        result: null,
        canonical_payload: {
          schema_version: 1,
          order_id: 'order-1',
          expected_version: 1,
          total_cents: 19900,
          currency: 'CNY',
          policy_version: 'demo-v1',
        },
      }
      if (state.losePrepare) {
        state.losePrepare = false
        throw new ApiError(0, 'NETWORK_ERROR', true)
      }
      return structuredClone(state.proposal)
    }
    if (path.endsWith('/confirmations')) {
      expect(body).toHaveProperty('decision')
      const decision = (body as { decision: 'approve' | 'reject' }).decision
      state.proposal!.confirmation = {
        confirmation_id: 'payment-confirmation',
        proposal_id: 'payment-1',
        decision,
        consumed_at: null,
        result_ref: null,
        decided_at: '2099-01-01T00:01:00Z',
      }
      state.proposal!.status = decision === 'approve' ? 'APPROVED' : 'REJECTED'
      if (state.loseConfirmation) {
        state.loseConfirmation = false
        throw new ApiError(0, 'NETWORK_ERROR', true)
      }
      return structuredClone(state.proposal!.confirmation) as Confirmation
    }
    if (path.endsWith('/mock-payments')) {
      expect(body).toEqual({
        proposal_id: 'payment-1',
        confirmation_id: 'payment-confirmation',
      })
      const receipt: MockPaymentReceipt = {
        action_type: 'MOCK_PAYMENT',
        action_id: 'payment-1',
        resource_id: 'order-1',
        order_id: 'order-1',
        total_cents: 19900,
        currency: 'CNY',
        created_at: '2099-01-01T00:02:00Z',
        status: state.decline ? 'DECLINED' : 'SUCCEEDED',
        payment_id: state.decline ? null : 'payment-row',
        order_status: state.decline ? 'PENDING_PAYMENT' : 'PAID',
      }
      state.proposal!.result = receipt
      state.proposal!.status = 'EXECUTED'
      if (!state.decline) state.order = { ...state.order, status: 'PAID', version: 2 }
      if (state.loseExecution) {
        state.loseExecution = false
        throw new ApiError(0, 'NETWORK_ERROR', true)
      }
      return receipt
    }
    throw new Error(`Unexpected ${method} ${path}`)
  }) as typeof api.request
  const calls = (suffix: string) =>
    vi.mocked(api.request).mock.calls.filter(([p, m]) => m === 'POST' && p.endsWith(suffix))
  return {
    api,
    state,
    calls,
    operation: createPaymentOperation(original),
    save: vi.fn(),
  }
}

describe('mock payment protocol', () => {
  it('prepares only a server quote; approval is a separate user action and confirmation', async () => {
    const f = fixture()
    const prepared = await preparePayment(f.api, original.id, f.operation, f.save)
    expect(prepared.proposal?.canonical_payload.total_cents).toBe(19900)
    expect(f.calls('/confirmations')).toHaveLength(0)
    expect(f.calls('/mock-payments')).toHaveLength(0)
    const paid = await decidePayment(f.api, original.id, f.operation, 'approve', f.save)
    expect(paid.receipt?.status).toBe('SUCCEEDED')
    expect(paid.order?.status).toBe('PAID')
    expect(f.operation.confirmation_id).toBe('payment-confirmation')
    expect(f.operation.confirmation_id).not.toBe('checkout-confirmation')
    expect(f.calls('/mock-payments')).toHaveLength(1)
  })
  it('replaying an approved operation reads the original receipt without a second payment', async () => {
    const f = fixture()
    await preparePayment(f.api, original.id, f.operation, f.save)
    await decidePayment(f.api, original.id, f.operation, 'approve', f.save)
    const again = await decidePayment(f.api, original.id, f.operation, 'approve', f.save)
    expect(again.receipt?.payment_id).toBe('payment-row')
    expect(f.calls('/confirmations')).toHaveLength(1)
    expect(f.calls('/mock-payments')).toHaveLength(1)
  })
  it('reject records a payment decision without calling the payment endpoint', async () => {
    const f = fixture()
    await preparePayment(f.api, original.id, f.operation, f.save)
    const rejected = await decidePayment(f.api, original.id, f.operation, 'reject', f.save)
    expect(rejected.proposal?.status).toBe('REJECTED')
    expect(rejected.order?.status).toBe('PENDING_PAYMENT')
    expect(f.calls('/mock-payments')).toHaveLength(0)
  })
  it('a committed payment with a lost response is recovered by GET only', async () => {
    const f = fixture()
    await preparePayment(f.api, original.id, f.operation, f.save)
    f.state.loseExecution = true
    const paid = await decidePayment(f.api, original.id, f.operation, 'approve', f.save)
    expect(paid.uncertain).toBe(false)
    expect(paid.receipt?.status).toBe('SUCCEEDED')
    expect(f.calls('/mock-payments')).toHaveLength(1)
  })
  it('lost confirmation requires explicit continuation, retaining the original confirmation', async () => {
    const f = fixture()
    await preparePayment(f.api, original.id, f.operation, f.save)
    f.state.loseConfirmation = true
    const lost = await decidePayment(f.api, original.id, f.operation, 'approve', f.save)
    expect(lost.uncertain).toBe(true)
    expect(f.calls('/mock-payments')).toHaveLength(0)
    expect(f.operation.confirmation_id).toBe('payment-confirmation')
    await decidePayment(f.api, original.id, f.operation, 'approve', f.save)
    expect(f.calls('/confirmations')).toHaveLength(1)
    expect(f.calls('/mock-payments')).toHaveLength(1)
  })
  it('lost proposal response reuses request_id, expected_version and key after reading the order', async () => {
    const f = fixture()
    f.state.losePrepare = true
    const lost = await preparePayment(f.api, original.id, f.operation, f.save)
    expect(lost.uncertain).toBe(true)
    expect(f.operation.proposal_id).toBeNull()
    const replay = await preparePayment(f.api, original.id, f.operation, f.save)
    expect(replay.proposal?.proposal_id).toBe('payment-1')
    const writes = f.calls('/payment-proposals')
    expect(writes).toHaveLength(2)
    expect(writes[1].slice(2, 4)).toEqual(writes[0].slice(2, 4))
    const paths = vi.mocked(f.api.request).mock.calls
    const firstPost = paths.findIndex(([p, m]) => p.endsWith('/payment-proposals') && m === 'POST')
    expect(paths.slice(0, firstPost)).toContainEqual(
      expect.arrayContaining(['/orders/order-1', 'GET']),
    )
  })
  it('unknown reads preserve identifiers and do not automatically repeat a write', async () => {
    const f = fixture()
    await preparePayment(f.api, original.id, f.operation, f.save)
    const before = { ...f.operation }
    f.state.failReads = true
    const unknown = await decidePayment(f.api, original.id, f.operation, 'approve', f.save)
    expect(unknown.uncertain).toBe(true)
    expect(f.calls('/mock-payments')).toHaveLength(0)
    expect(f.operation.request_id).toBe(before.request_id)
    expect(f.operation.execute_key).toBe(before.execute_key)
  })
  it('decline remains a real DECLINED receipt, never a paid order', async () => {
    const f = fixture()
    await preparePayment(f.api, original.id, f.operation, f.save)
    f.state.decline = true
    const result = await decidePayment(f.api, original.id, f.operation, 'approve', f.save)
    expect(result.receipt?.status).toBe('DECLINED')
    expect(result.receipt?.payment_id).toBeNull()
    expect(result.order?.status).toBe('PENDING_PAYMENT')
  })
  it('server expiry prevents confirmation regardless of the local clock', async () => {
    const f = fixture()
    await preparePayment(f.api, original.id, f.operation, f.save)
    f.state.proposal!.status = 'EXPIRED'
    const result = await decidePayment(f.api, original.id, f.operation, 'approve', f.save)
    expect(result.error?.code).toBe('STALE_PROPOSAL')
    expect(f.calls('/confirmations')).toHaveLength(0)
    expect(f.calls('/mock-payments')).toHaveLength(0)
  })
  it('a stale version stops writes instead of silently replacing the expected version', async () => {
    const f = fixture()
    await preparePayment(f.api, original.id, f.operation, f.save)
    f.state.order.version = 2
    const result = await decidePayment(f.api, original.id, f.operation, 'approve', f.save)
    expect(result.error?.code).toBe('STALE_VERSION')
    expect(f.operation.expected_version).toBe(1)
    expect(f.calls('/confirmations')).toHaveLength(0)
    expect(f.calls('/mock-payments')).toHaveLength(0)
  })
  it('permission denial never issues a payment or invents a receipt', async () => {
    const f = fixture()
    f.state.forbidden = true
    const denied = await preparePayment(f.api, original.id, f.operation, f.save)
    expect(denied.error?.status).toBe(403)
    expect(denied.receipt).toBeNull()
    expect(f.calls('/payment-proposals')).toHaveLength(0)
  })
  it('receipt-time PAID does not replace the latest server order status', async () => {
    const f = fixture()
    await preparePayment(f.api, original.id, f.operation, f.save)
    await decidePayment(f.api, original.id, f.operation, 'approve', f.save)
    f.state.order = { ...f.state.order, status: 'SHIPPED', version: 3 }
    const read = await readPaymentOutcome(f.api, original.id, f.operation)
    expect(read.receipt?.order_status).toBe('PAID')
    expect(read.order?.status).toBe('SHIPPED')
  })
})

describe('payment reference privacy', () => {
  it('serializes only operation references, never accidental credentials or order data', () => {
    const f = fixture()
    const setItem = vi.fn()
    const polluted = Object.assign({}, f.operation, {
      token: 'synthetic-private-token',
      address: 'synthetic-private-address',
    })
    storePaymentOperation({ setItem }, 'payment', polluted)
    const serialized = setItem.mock.calls[0][1] as string
    expect(serialized).not.toContain('synthetic-private')
    expect(serialized).not.toContain('token')
    expect(JSON.parse(serialized).request_id).toBe(f.operation.request_id)
  })
  it('rejects corrupted or extra-field references instead of silently starting a new operation', () => {
    const f = fixture()
    expect(() =>
      loadPaymentOperation(
        { getItem: () => JSON.stringify({ ...f.operation, token: 'synthetic-private-token' }) },
        'payment',
        original.id,
      ),
    ).toThrow()
    expect(() =>
      loadPaymentOperation({ getItem: () => '{broken' }, 'payment', original.id),
    ).toThrow('本地付款引用无法核验')
    expect(() =>
      loadPaymentOperation(
        { getItem: () => JSON.stringify({ ...f.operation, expected_version: 0 }) },
        'payment',
        original.id,
      ),
    ).toThrow()
  })
  it('separates user, store and order references without persisting authentication', () => {
    const u = { user_id: 'u1', store_id: 's1', role: 'buyer' as const }
    expect(paymentStorageKey(u, 'o1')).not.toBe(paymentStorageKey({ ...u, user_id: 'u2' }, 'o1'))
    expect(paymentStorageKey(u, 'o1')).not.toBe(paymentStorageKey({ ...u, store_id: 's2' }, 'o1'))
    expect(paymentStorageKey(u, 'o1')).not.toBe(paymentStorageKey(u, 'o2'))
  })
})

it('reads the order after the receipt, so a commit cannot pair success with an older pending read', async () => {
  const f = fixture()
  await preparePayment(f.api, original.id, f.operation, f.save)
  await decidePayment(f.api, original.id, f.operation, 'approve', f.save)
  let commitObserved = false
  f.api.request = vi.fn(async (path: string, method: string) => {
    expect(method).toBe('GET')
    if (path === '/proposals/payment-1') {
      commitObserved = true
      return structuredClone(f.state.proposal)
    }
    if (path === '/orders/order-1')
      return {
        ...original,
        status: commitObserved ? 'PAID' : 'PENDING_PAYMENT',
        version: commitObserved ? 2 : 1,
      }
    throw new Error('unexpected API')
  }) as typeof f.api.request
  const result = await readPaymentOutcome(f.api, original.id, f.operation)
  expect(result.receipt?.status).toBe('SUCCEEDED')
  expect(result.order?.status).toBe('PAID')
})
