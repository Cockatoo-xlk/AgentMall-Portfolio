import { ApiClient, ApiError } from './client'
import type { Confirmation, MockPaymentProposal, MockPaymentReceipt, Order, User } from './types'

export interface PaymentOperation {
  request_id: string
  order_id: string
  expected_version: number
  prepare_key: string
  execute_key: string
  proposal_id: string | null
  confirmation_id: string | null
  decision: 'approve' | 'reject' | null
  phase:
    | 'new'
    | 'preparing'
    | 'proposal'
    | 'confirming'
    | 'approved'
    | 'executing'
    | 'complete'
    | 'rejected'
    | 'blocked'
}
export interface PaymentOutcome {
  order: Order | null
  proposal: MockPaymentProposal | null
  receipt: MockPaymentReceipt | null
  error: ApiError | null
  uncertain: boolean
}
type Save = (operation: PaymentOperation) => void
const asError = (e: unknown) => (e instanceof ApiError ? e : new ApiError(0, 'NETWORK_ERROR', true))
const uncertainError = (e: ApiError) => e.ambiguous || e.status === 0 || e.status >= 500
export function createPaymentOperation(order: Order): PaymentOperation {
  if (order.status !== 'PENDING_PAYMENT') throw new ApiError(409, 'INVALID_ORDER_STATE')
  const request_id = crypto.randomUUID()
  return {
    request_id,
    order_id: order.id,
    expected_version: order.version,
    prepare_key: `web:payment:proposal:${request_id}`,
    execute_key: `web:payment:execute:${request_id}`,
    proposal_id: null,
    confirmation_id: null,
    decision: null,
    phase: 'new',
  }
}
function validateProposal(proposal: MockPaymentProposal, orderId: string, op: PaymentOperation) {
  if (
    !proposal ||
    proposal.action_type !== 'MOCK_PAYMENT' ||
    proposal.schema_version !== 1 ||
    proposal.canonical_payload?.order_id !== orderId ||
    op.order_id !== orderId ||
    proposal.canonical_payload.expected_version !== op.expected_version ||
    (op.proposal_id && proposal.proposal_id !== op.proposal_id) ||
    (proposal.confirmation && proposal.confirmation.proposal_id !== proposal.proposal_id)
  )
    throw new ApiError(409, 'SNAPSHOT_MISMATCH')
  const r = proposal.result
  if (
    r &&
    (r.action_type !== 'MOCK_PAYMENT' ||
      r.action_id !== proposal.proposal_id ||
      r.order_id !== orderId ||
      r.resource_id !== orderId ||
      r.total_cents !== proposal.canonical_payload.total_cents ||
      r.currency !== proposal.canonical_payload.currency)
  )
    throw new ApiError(409, 'SNAPSHOT_MISMATCH')
}
function remember(op: PaymentOperation, result: PaymentOutcome, save: Save) {
  if (result.proposal?.confirmation) {
    op.confirmation_id = result.proposal.confirmation.confirmation_id
    op.decision = result.proposal.confirmation.decision
  }
  if (result.receipt && result.order && !result.error) op.phase = 'complete'
  else if (result.proposal?.confirmation?.decision === 'reject') op.phase = 'rejected'
  else if (result.proposal?.confirmation?.decision === 'approve' && op.phase !== 'executing')
    op.phase = 'approved'
  save({ ...op })
}
export async function readPaymentOutcome(
  client: ApiClient,
  orderId: string,
  op: PaymentOperation,
): Promise<PaymentOutcome> {
  const result: PaymentOutcome = {
    order: null,
    proposal: null,
    receipt: null,
    error: null,
    uncertain: false,
  }
  // The proposal GET may wait for an in-flight transaction. Read the order
  // afterwards so its state cannot predate a newly recovered committed receipt.
  if (op.proposal_id) {
    try {
      const proposal = await client.get<MockPaymentProposal>(
        `/proposals/${encodeURIComponent(op.proposal_id)}`,
      )
      validateProposal(proposal, orderId, op)
      result.proposal = proposal
      result.receipt = proposal.result
    } catch (e) {
      result.error = asError(e)
    }
  }
  try {
    const order = await client.get<Order>(`/orders/${encodeURIComponent(orderId)}`)
    if (order.id === orderId) result.order = order
    else result.error ??= new ApiError(409, 'SNAPSHOT_MISMATCH')
  } catch (e) {
    result.error ??= asError(e)
  }
  if (
    !result.receipt &&
    result.order?.status === 'PENDING_PAYMENT' &&
    result.proposal &&
    result.order.version !== result.proposal.canonical_payload.expected_version
  )
    result.error ??= new ApiError(409, 'STALE_VERSION')
  result.uncertain = !!result.error && uncertainError(result.error)
  if (
    !result.receipt &&
    (op.phase === 'executing' ||
      (op.phase === 'preparing' && !result.proposal) ||
      (op.phase === 'confirming' && !result.proposal?.confirmation))
  )
    result.uncertain = true
  return result
}
async function recover(
  client: ApiClient,
  orderId: string,
  op: PaymentOperation,
  save: Save,
  error: unknown,
) {
  const result = await readPaymentOutcome(client, orderId, op)
  if (result.receipt && result.order && !result.error) {
    result.uncertain = false
  } else {
    const original = asError(error)
    result.error ??= original
    result.uncertain ||= uncertainError(original)
    if (!uncertainError(original)) op.phase = 'blocked'
  }
  remember(op, result, save)
  return result
}
export async function preparePayment(
  client: ApiClient,
  orderId: string,
  op: PaymentOperation,
  save: Save,
): Promise<PaymentOutcome> {
  const before = await readPaymentOutcome(client, orderId, op)
  if (before.error || op.proposal_id) {
    remember(op, before, save)
    return before
  }
  try {
    if (before.order?.status !== 'PENDING_PAYMENT') throw new ApiError(409, 'INVALID_ORDER_STATE')
    if (before.order.version !== op.expected_version) throw new ApiError(409, 'STALE_VERSION')
    op.phase = 'preparing'
    save({ ...op })
    const proposal = await client.post<MockPaymentProposal>(
      `/orders/${encodeURIComponent(orderId)}/payment-proposals`,
      {
        request_id: op.request_id,
        proposal_slot: 'web_payment',
        expected_version: op.expected_version,
      },
      op.prepare_key,
    )
    validateProposal(proposal, orderId, op)
    op.proposal_id = proposal.proposal_id
    op.phase = 'proposal'
    save({ ...op })
    const result = await readPaymentOutcome(client, orderId, op)
    remember(op, result, save)
    return result
  } catch (e) {
    return recover(client, orderId, op, save, e)
  }
}
export async function decidePayment(
  client: ApiClient,
  orderId: string,
  op: PaymentOperation,
  decision: 'approve' | 'reject',
  save: Save,
): Promise<PaymentOutcome> {
  const before = await readPaymentOutcome(client, orderId, op)
  if (before.error || before.receipt) {
    remember(op, before, save)
    return before
  }
  try {
    const p = before.proposal
    if (!p) throw new ApiError(409, 'PROPOSAL_REQUIRED')
    if (p.status === 'EXPIRED') throw new ApiError(409, 'STALE_PROPOSAL')
    if (p.status === 'REJECTED' || p.confirmation?.decision === 'reject') {
      if (decision === 'reject') {
        remember(op, before, save)
        return before
      }
      throw new ApiError(409, 'DECISION_CONFLICT')
    }
    if (before.order?.status !== 'PENDING_PAYMENT') throw new ApiError(409, 'INVALID_ORDER_STATE')
    if (op.decision && op.decision !== decision) throw new ApiError(409, 'DECISION_CONFLICT')
    if (p.confirmation && p.confirmation.decision !== decision)
      throw new ApiError(409, 'DECISION_CONFLICT')
    op.decision = decision
    let confirmation = p.confirmation
    if (!confirmation) {
      if (op.confirmation_id) throw new ApiError(409, 'CONFIRMATION_REQUIRED')
      op.phase = 'confirming'
      save({ ...op })
      confirmation = await client.post<Confirmation>(
        `/proposals/${encodeURIComponent(p.proposal_id)}/confirmations`,
        { decision },
      )
    }
    if (
      confirmation.proposal_id !== p.proposal_id ||
      confirmation.decision !== decision ||
      (op.confirmation_id && op.confirmation_id !== confirmation.confirmation_id)
    )
      throw new ApiError(409, 'SNAPSHOT_MISMATCH')
    op.confirmation_id = confirmation.confirmation_id
    op.phase = decision === 'approve' ? 'approved' : 'rejected'
    save({ ...op })
    if (decision === 'reject') {
      const result = await readPaymentOutcome(client, orderId, op)
      remember(op, result, save)
      return result
    }
    // A second read can discover an already-completed payment or a concurrent order change.
    const confirmed = await readPaymentOutcome(client, orderId, op)
    if (confirmed.error || confirmed.receipt) {
      remember(op, confirmed, save)
      return confirmed
    }
    if (
      confirmed.order?.status !== 'PENDING_PAYMENT' ||
      confirmed.proposal?.status !== 'APPROVED' ||
      confirmed.proposal.confirmation?.confirmation_id !== op.confirmation_id
    )
      throw new ApiError(409, 'CONFIRMATION_REQUIRED')
    op.phase = 'executing'
    save({ ...op })
    await client.post<MockPaymentReceipt>(
      `/orders/${encodeURIComponent(orderId)}/mock-payments`,
      {
        proposal_id: p.proposal_id,
        confirmation_id: op.confirmation_id,
      },
      op.execute_key,
    )
    const result = await readPaymentOutcome(client, orderId, op)
    remember(op, result, save)
    return result
  } catch (e) {
    return recover(client, orderId, op, save, e)
  }
}

export const paymentStorageKey = (user: User, orderId: string) =>
  `agentmall:mock-payment:${user.user_id}:${user.store_id}:${orderId}`
const referenceFields = [
  'request_id',
  'order_id',
  'expected_version',
  'prepare_key',
  'execute_key',
  'proposal_id',
  'confirmation_id',
  'decision',
  'phase',
] as const
export function storePaymentOperation(
  storage: Pick<Storage, 'setItem'>,
  key: string,
  operation: PaymentOperation,
) {
  const references = Object.fromEntries(referenceFields.map((field) => [field, operation[field]]))
  storage.setItem(key, JSON.stringify(references))
}
export function loadPaymentOperation(
  storage: Pick<Storage, 'getItem'>,
  key: string,
  orderId: string,
): PaymentOperation | null {
  const raw = storage.getItem(key)
  if (!raw) return null
  const invalid = () => new Error('本地付款引用无法核验，请先查询订单，不会自动重试。')
  let value: PaymentOperation
  try {
    value = JSON.parse(raw) as PaymentOperation
  } catch {
    throw invalid()
  }
  if (
    !value ||
    raw.length > 4096 ||
    Object.keys(value).length !== referenceFields.length ||
    Object.keys(value).some((field) => !(referenceFields as readonly string[]).includes(field)) ||
    value.order_id !== orderId ||
    typeof value.request_id !== 'string' ||
    !/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i.test(value.request_id) ||
    !Number.isInteger(value.expected_version) ||
    value.expected_version < 1 ||
    value.prepare_key !== `web:payment:proposal:${value.request_id}` ||
    value.execute_key !== `web:payment:execute:${value.request_id}` ||
    ![
      'new',
      'preparing',
      'proposal',
      'confirming',
      'approved',
      'executing',
      'complete',
      'rejected',
      'blocked',
    ].includes(value.phase) ||
    ![null, 'approve', 'reject'].includes(value.decision) ||
    ![value.proposal_id, value.confirmation_id].every(
      (v) => v === null || (typeof v === 'string' && /^[A-Za-z0-9_.:-]{1,128}$/.test(v)),
    )
  )
    throw invalid()
  return value
}
