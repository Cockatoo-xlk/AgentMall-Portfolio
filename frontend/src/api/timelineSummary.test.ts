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
  it('separates a received usage observation from unfinished budget reconciliation', () => {
    const summary = timelineSummary(event('model_end', { status: 'failed', usage: 'UNKNOWN', observed_provider_usage: { input_tokens: 20, output_tokens: 5 }, provider_usage_state: 'OBSERVED_VALID', output_budget_state: 'UNRESOLVED', diagnostic_stage: 'SDK_RESPONSE_PARSE' }))
    expect(summary).toContain('Usage UNKNOWN')
    expect(summary).toContain('响应观测 20 / 5')
    expect(summary).toContain('预算未核对完成')
    expect(summary).not.toContain('已结算')
  })
  it('shows batch refusal without inventing business rollback', () => {
    expect(timelineSummary(event('tool_batch_rejected', { diagnostic_code: 'TOOL_ARGUMENT_SCHEMA_INVALID', tools_executed: false }))).toBe('工具参数不符合 Schema · 本批工具未执行')
    expect(timelineSummary(event('tool_batch_rejected', {}))).toContain('执行状态待核对')
  })
})
