import { describe, it, expect, vi } from 'vitest'
import { ApiClient } from './client'
import { decide, mergeEvents } from './agentWorkflow'
import type { Run, RunEvent, Operation } from './agentWorkflow'
const pending = {
  interrupt_id: 'first',
  proposal_id: 'p1',
  type: 'confirmation',
  action_type: 'CHECKOUT',
}
const run = {
  id: 'r1',
  thread_id: 't1',
  pending_confirmation: pending,
  status: 'WAITING_INPUT',
} as Run
const op: Operation = {
  request_id: 'stable',
  run_id: 'r1',
  interrupt_id: 'first',
  proposal_id: 'p1',
  decision: 'approve',
}
function client(handler: (path: string, method: string, body: unknown) => unknown) {
  const api = new ApiClient()
  api.request = vi.fn(async (p, m, b) => handler(p, m, b)) as typeof api.request
  return api
}
describe('durable workflow protocol', () => {
  it('deduplicates incremental events while keeping earlier data', () => {
    const events = [{ seq: 1 }, { seq: 2 }] as RunEvent[]
    expect(mergeEvents(events, [{ seq: 2 }, { seq: 3 }] as RunEvent[]).map((e) => e.seq)).toEqual([
      1, 2, 3,
    ])
  })
  it('old interrupt cannot approve the next proposal', async () => {
    const api = client((p, m) => {
      expect(m).toBe('GET')
      expect(p).toBe('/agent/threads/t1')
      return {
        id: 't1',
        runs: [
          {
            ...run,
            pending_confirmation: { ...pending, interrupt_id: 'second', proposal_id: 'p2' },
          },
        ],
      }
    })
    const result = await decide(api, 't1', op, () => {})
    expect(result.thread.runs[0].pending_confirmation?.proposal_id).toBe('p2')
  })
  it('lost committed resume is reconciled without a new write or request ID', async () => {
    let resumed = false
    const paths: string[] = []
    const api = client((p, m, b) => {
      paths.push(`${m} ${p}`)
      if (p === '/agent/threads/t1')
        return {
          id: 't1',
          runs: [
            {
              ...run,
              status: resumed ? 'COMPLETED' : 'WAITING_INPUT',
              pending_confirmation: resumed ? null : pending,
            },
          ],
        }
      if (p === '/proposals/p1')
        return { proposal_id: 'p1', status: resumed ? 'EXECUTED' : 'PENDING', confirmation: null }
      if (p.endsWith('/confirmations')) return { confirmation_id: 'c1', decision: 'approve' }
      if (p.endsWith('/resume')) {
        expect(b).toEqual({
          request_id: 'stable',
          run_id: 'r1',
          interrupt_id: 'first',
          proposal_id: 'p1',
          confirmation_id: 'c1',
        })
        resumed = true
        throw new Error('lost')
      }
      throw new Error('unexpected API')
    })
    const result = await decide(api, 't1', { ...op }, () => {})
    expect(result.thread.runs[0].status).toBe('COMPLETED')
    expect(result.uncertain).toBe(false)
    expect(paths.filter((p) => p.startsWith('POST'))).toEqual([
      'POST /proposals/p1/confirmations',
      'POST /agent/threads/t1/resume',
    ])
  })
})

it('recommendation retry retains original constraints and excludes returned products without write intents', async () => {
  const { recommendation } = await import('./agentWorkflow')
  const next = recommendation({
    ...run,
    constraints: {
      max_price_cents: 20000,
      category: 'keyboard',
      product_needs: { layout: '87键' },
      exclude_product_ids: [],
      return_requested: true,
      purchase_requested: true,
    },
    result: {
      answer: '',
      execution_mode: 'FIXTURE',
      error_codes: [],
      unfinished: [],
      citations: [],
      facts: [],
      entity_refs: [
        { kind: 'order', id: 'owned-order', relation: 'original' },
        { kind: 'product', id: 'returned-product', relation: 'original' },
      ],
    },
  } as Run)
  expect(next.constraints).toMatchObject({
    max_price_cents: 20000,
    category: 'keyboard',
    product_needs: { layout: '87键' },
    exclude_product_ids: ['returned-product'],
    exclude_original: true,
    return_requested: false,
    purchase_requested: false,
    support_requested: false,
  })
  expect(next.message).toContain('owned-order')
  expect(next.message).not.toContain('500')
})
