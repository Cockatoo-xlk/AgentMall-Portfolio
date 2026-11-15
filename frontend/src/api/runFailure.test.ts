import { describe, expect, it } from 'vitest'
import { runFailure } from './runFailure'

describe('CONTRACT_TEST_ONLY: explain failures without granting actions', () => {
  it('explains schema and parsing failures separately', () => {
    expect(runFailure('INVALID_TOOL_BATCH')).toContain('工具调用')
    expect(runFailure('MODEL_RESPONSE_INVALID')).toContain('解析')
    expect(runFailure('AFTERSALES_INELIGIBLE')).toContain('资格')
  })
  it('keeps unknown causes unknown and never repeats arbitrary text', () => {
    expect(runFailure('PRIVATE_UNKNOWN_TEXT')).toBe('此步骤未完成，具体原因待核对。')
    expect(runFailure(null)).toBe('')
  })
  it('does not claim refunds, rollback or supplier settlement', () => {
    for (const code of ['MODEL_RESPONSE_INVALID', 'MODEL_USAGE_INVALID', 'AFTERSALES_INELIGIBLE', 'CONTEXT_SCOPE_VIOLATION']) {
      expect(runFailure(code)).not.toMatch(/已退款|已撤销|已付款|已结算|自动重试/)
    }
  })
})
