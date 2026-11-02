import { ApiClient } from './client'
import type { ThreadContext } from './threadContext'
import type { Confirmation, Proposal } from './types'
export interface EntityRef {
  kind: 'product' | 'order' | 'proposal' | 'case' | 'ticket'
  id: string
  relation?: string
  policy_version?: string
}
export interface Citation {
  id?: string
  document_id: string
  title: string
  section_id: string
  source_uri: string
  policy_version: string
  text: string
  visibility: string
}
export interface Pending {
  type: string
  interrupt_id: string
  proposal_id?: string
  action_type?: string
}
export interface Run {
  constraints: Record<string, unknown>
  id: string
  thread_id: string
  request_id: string
  status: 'RUNNING' | 'WAITING_INPUT' | 'COMPLETED' | 'PARTIAL' | 'FAILED'
  last_error: string | null
  pending_confirmation: Pending | null
  model_id: string
  budget: Record<string, number>
  result: null | {
    answer: string
    execution_mode: string
    error_codes: string[]
    unfinished: string[]
    entity_refs: EntityRef[]
    citations: Citation[]
    facts: { kind: string; id: string; data: Record<string, unknown> }[]
  }
}
export interface Thread {
  id: string
  mode: 'single' | 'multi'
  status: string
  context?: ThreadContext
  runs: Run[]
}
export interface RunEvent {
  id: string
  seq: number
  event_type: string
  agent: string | null
  action_id: string | null
  timestamp: string
  payload_summary: Record<string, unknown>
}
export interface EventPage {
  items: RunEvent[]
  next_seq: number
}
export interface Operation {
  request_id: string
  run_id: string
  interrupt_id: string
  proposal_id: string
  confirmation_id?: string
  decision: 'approve' | 'reject'
}
export const uuidPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i
export function mergeEvents(previous: RunEvent[], incoming: RunEvent[]) {
  return [...new Map([...previous, ...incoming].map((event) => [event.seq, event])).values()].sort(
    (a, b) => a.seq - b.seq,
  )
}
export function currentInterrupt(thread: Thread, op: Operation) {
  const latest = thread.runs[0]
  return (
    latest?.id === op.run_id &&
    latest.pending_confirmation?.interrupt_id === op.interrupt_id &&
    latest.pending_confirmation?.proposal_id === op.proposal_id
  )
}
export async function decide(
  api: ApiClient,
  threadId: string,
  op: Operation,
  save: (op: Operation) => void,
) {
  let thread = await api.get<Thread>(`/agent/threads/${threadId}`)
  if (!currentInterrupt(thread, op)) return { thread, uncertain: false }
  let proposal = await api.get<Proposal>(`/proposals/${op.proposal_id}`)
  if (proposal.status === 'EXPIRED') throw new Error('提案已过期，需要新提案和重新确认。')
  let confirmation = proposal.confirmation
  if (!confirmation) {
    try {
      confirmation = await api.post<Confirmation>(`/proposals/${op.proposal_id}/confirmations`, {
        decision: op.decision,
      })
    } catch (error) {
      // No blind confirmation replay: read the durable decision first.
      proposal = await api.get<Proposal>(`/proposals/${op.proposal_id}`)
      confirmation = proposal.confirmation
      if (!confirmation) throw error
    }
  }
  if (
    confirmation.decision !== op.decision ||
    (op.confirmation_id && confirmation.confirmation_id !== op.confirmation_id)
  )
    throw new Error('服务端已有不同决定，请核对当前提案。')
  op = { ...op, confirmation_id: confirmation.confirmation_id }
  save(op)
  // Recheck after confirmation: another browser may have resumed to the next interrupt.
  thread = await api.get<Thread>(`/agent/threads/${threadId}`)
  if (!currentInterrupt(thread, op)) return { thread, uncertain: false }
  try {
    await api.post<Run>(`/agent/threads/${threadId}/resume`, {
      request_id: op.request_id,
      run_id: op.run_id,
      interrupt_id: op.interrupt_id,
      proposal_id: op.proposal_id,
      confirmation_id: op.confirmation_id,
    })
  } catch {
    // Resume may have committed. GET failure propagates as unknown, never business failure.
    thread = await api.get<Thread>(`/agent/threads/${threadId}`)
    await api.get<Proposal>(`/proposals/${op.proposal_id}`)
    return { thread, uncertain: currentInterrupt(thread, op) }
  }
  thread = await api.get<Thread>(`/agent/threads/${threadId}`)
  await api.get<Proposal>(`/proposals/${op.proposal_id}`)
  return { thread, uncertain: false }
}
export function operationKey(owner: string, thread: string, pending: Pending) {
  return `agentmall:resume:${owner}:${thread}:${pending.interrupt_id}`
}
export function readOperation(key: string, run: Run): Operation | null {
  try {
    const op = JSON.parse(sessionStorage.getItem(key) ?? 'null') as Operation | null
    return op &&
      uuidPattern.test(op.request_id) &&
      op.run_id === run.id &&
      op.interrupt_id === run.pending_confirmation?.interrupt_id &&
      op.proposal_id === run.pending_confirmation?.proposal_id &&
      ['approve', 'reject'].includes(op.decision)
      ? op
      : null
  } catch {
    return null
  }
}
export function saveOperation(key: string, op: Operation) {
  try {
    sessionStorage.setItem(key, JSON.stringify(op))
  } catch {
    /* Memory still keeps this operation stable. */
  }
}

export function recoverable(run: Run) {
  return (
    run.status === 'RUNNING' ||
    ['EXECUTION_INTERRUPTED', 'EXECUTION_TIMEOUT', 'DATABASE_UNAVAILABLE'].includes(
      run.last_error ?? '',
    )
  )
}
export function recommendation(run: Run) {
  if (!run.constraints) throw new Error('缺少原需求快照，请明确新需求后启动独立 Run。')
  const originals = run.result?.entity_refs.filter((r) => r.relation === 'original') ?? []
  const orders = originals.filter((r) => r.kind === 'order')
  return {
    message: `${orders.map((r) => `订单${r.id}`).join('，')}，只做替代商品推荐，不要购买，不要申请退货，不要联系人工。`,
    constraints: {
      ...run.constraints,
      exclude_product_ids: [
        ...new Set([
          ...(Array.isArray(run.constraints.exclude_product_ids)
            ? run.constraints.exclude_product_ids
            : []),
          ...originals.filter((r) => r.kind === 'product').map((r) => r.id),
        ]),
      ],
      exclude_original: Boolean(run.constraints.exclude_original || orders.length),
      purchase_requested: false,
      return_requested: false,
      support_requested: false,
      support_declined: true,
      address_label: null,
    },
  }
}
