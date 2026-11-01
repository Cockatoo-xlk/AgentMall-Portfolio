import type { RunEvent } from './agentWorkflow'
const agents: Record<string, string> = {
  supervisor: 'Supervisor',
  shopping: 'Shopping',
  order: 'Order',
  aftersales: 'AfterSales',
  single: 'Single',
}
const goals: Record<string, string> = {
  find_products: '检索商品',
  inspect_orders: '核对订单',
  prepare_checkout: '准备购买提案',
  assess_return: '核对售后资格',
  prepare_return: '准备退货提案',
  human_support: '人工接管',
}
export function timelineSummary(event: RunEvent): string {
  const p = event.payload_summary
  if (event.event_type === 'route_decision') {
    if (p.terminal === 'finish') return 'Supervisor · 完成当前工作流'
    return Array.isArray(p.tasks)
      ? p.tasks
          .map((t) => `${agents[t.target] ?? 'Agent'} · ${goals[t.goal] ?? '专业任务'}`)
          .join('；')
      : '路由详情待核对'
  }
  if (event.event_type === 'handoff')
    return `${agents[String(p.target)] ?? 'Agent'} · ${goals[String(p.goal)] ?? '专业任务'}`
  if (event.event_type === 'tool')
    return `${p.name ?? '工具'} · ${p.ok === true ? '成功' : p.ok === false ? '失败' : '结果待核对'}${Number.isSafeInteger(p.duration_ms) ? ` · ${p.duration_ms} ms` : ''}`
  if (event.event_type === 'model_start')
    return `模型请求 #${p.attempt ?? 'UNKNOWN'} · Usage UNKNOWN（尚未收到回执）`
  if (event.event_type === 'model_end') {
    const usage = p.usage as { input_tokens?: number; output_tokens?: number } | undefined
    return `${p.status === 'completed' ? '有效返回' : '错误或未知返回'} · ${usage && typeof usage === 'object' && Number.isSafeInteger(usage.input_tokens) && Number.isSafeInteger(usage.output_tokens) ? `${usage.input_tokens} / ${usage.output_tokens} tokens（输入 / 输出）` : 'Usage UNKNOWN'}`
  }
  return ''
}
