import { describe, it, expect } from 'vitest'
import { timelineSummary } from './timelineSummary'
import type { RunEvent } from './agentWorkflow'
const event = (event_type: string, payload_summary: Record<string, unknown>): RunEvent => ({
  id: 'e',
  seq: 1,
  event_type,
  payload_summary,
  agent: null,
  action_id: null,
  timestamp: '2026-11-01T00:00:00Z',
})
describe('readable persisted event summaries', () => {
  it('shows model chosen routes and handoff targets', () => {
    expect(
      timelineSummary(
        event('route_decision', { tasks: [{ target: 'shopping', goal: 'find_products' }] }),
      ),
    ).toContain('Shopping')
    expect(
      timelineSummary(event('handoff', { target: 'order', goal: 'prepare_checkout' })),
    ).toContain('准备购买提案')
  })
  it('shows tool outcome and duration without adding model prose', () => {
    expect(
      timelineSummary(
        event('tool', {
          name: 'retrieve_products',
          ok: true,
          duration_ms: 16,
          reasoning: 'private',
        }),
      ),
    ).toBe('retrieve_products · 成功 · 16 ms')
    expect(timelineSummary(event('tool', { name: 'prepare_checkout', ok: false }))).toContain(
      '失败',
    )
  })
  it('never invents token usage when unknown', () => {
    expect(
      timelineSummary(event('model_end', { status: 'completed', usage: 'UNKNOWN' })),
    ).toContain('UNKNOWN')
    expect(
      timelineSummary(
        event('model_end', {
          status: 'completed',
          usage: { input_tokens: 10, output_tokens: 2, total_tokens: 12 },
        }),
      ),
    ).toContain('10 / 2 tokens')
  })
})
