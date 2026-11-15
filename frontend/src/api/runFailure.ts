const explanations: Record<string, string> = {
  INVALID_TOOL_BATCH: '模型工具调用不符合契约，已拒绝该批次；请核对已有业务回执。',
  UNORDERED_WRITE_BATCH: '一个批次包含不能同时执行的写入，已拒绝该批次。',
  MODEL_RESPONSE_INVALID: '模型响应无法按 SDK 协议解析，当前步骤已停止。',
  MODEL_USAGE_INVALID: '模型用量无法通过校验，当前步骤已停止；费用状态需另行核对。',
  AFTERSALES_INELIGIBLE: '本次售后资格校验未通过，请核对订单、有效期及已有售后申请。',
  RETURN_NOT_REQUESTED: '本轮没有明确的退货申请意图，需要先说明当前决定。',
  PURCHASE_DETAILS_REQUIRED: '购买提案缺少明确的商品、数量或演示地址。',
  CONTEXT_SCOPE_VIOLATION: '交接包含目标角色不可见的引用，已拒绝派发。',
  HANDOFF_CONSTRAINT_CHANGED: '交接改变了已验证的用户约束，已拒绝派发。',
  BUDGET_EXCEEDED: '本轮调用或时间预算已用完，未继续执行未完成步骤。',
}

export function runFailure(code: string | null): string {
  return code ? explanations[code] ?? '此步骤未完成，具体原因待核对。' : ''
}
