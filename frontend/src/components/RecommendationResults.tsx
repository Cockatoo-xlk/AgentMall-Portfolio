import type { Run } from '../api/agentWorkflow'
import { attributeLabels, attributeValue, categoryLabels } from '../api/catalog'
import { money } from '../api/format'
import './RecommendationResults.css'

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
}
function count(value: unknown): number | null {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0 ? value : null
}
function text(value: unknown): string {
  if (typeof value === 'string' && value) return value
  if (typeof value === 'number' && Number.isFinite(value)) return String(value)
  if (Array.isArray(value) && value.every(item => typeof item === 'string')) return attributeValue(value)
  return 'UNKNOWN'
}

export default function RecommendationResults({ run }: { run: Run }) {
  const c = run.constraints
  const needs = record(c.product_needs)
  const requirements = record(c.recommendation)
  const requested = count(requirements.count)
  const budget = count(c.max_price_cents)
  const exclusions = Array.isArray(needs.excluded_connections)
    ? needs.excluded_connections.filter((item): item is string => typeof item === 'string') : []
  const identifiers = [...new Set(run.result?.entity_refs
    .filter(ref => ref.kind === 'product' && ref.relation === 'replacement').map(ref => ref.id) ?? [])]
  const facts = new Map(run.result?.facts.filter(fact => fact.kind === 'product').map(fact => [fact.id, fact.data]))
  const candidates = identifiers.flatMap(id => {
    const data = facts.get(id)
    return data ? [{ id, data, attributes: record(data.attributes) }] : []
  })
  const attributes = [...new Set(candidates.flatMap(item => Object.keys(item.attributes)))]
  const missing = identifiers.length - candidates.length
  const shortage = run.result && run.status !== 'RUNNING' && requested !== null && requested > candidates.length
  return <section className="panel stack recommendation-results" aria-label="推荐结果与商品对比" data-testid="recommendation-results">
    <span className="eyebrow">RECOMMENDATION · SERVER SNAPSHOT</span>
    <h2>需求与候选对比</h2>
    <div data-testid="recommendation-constraints">
      <p>品类：{(categoryLabels as Record<string, string>)[String(c.category)] ?? '未指定'} · 预算：{budget === null ? '未指定' : money(budget)} · 噪声：{c.noise_preference === 'quiet' ? '静音偏好' : text(c.noise_preference) === 'UNKNOWN' ? '未指定' : text(c.noise_preference)}</p>
      {Object.entries(needs).filter(([key, value]) => key !== 'excluded_connections' && value != null && value !== '').map(([key, value]) => <p key={key}>{attributeLabels[key] ?? key}：{text(value)}</p>)}
      {exclusions.length > 0 && <p>排除连接标签：{exclusions.join('、')}</p>}
      {requirements.compare_connections === true && <p>已请求有线 / 无线连接方式对比；以下仅呈现服务端商品属性。</p>}
    </div>
    <p data-testid="candidate-count">{requested === null || requested === 0 ? '请求数量未指定' : `请求 ${requested} 款`} · 已核验候选 {candidates.length} 款</p>
    {missing > 0 && <p className="notice warning">{missing} 款引用缺少商品快照，未计入已核验候选。</p>}
    {shortage && <p className="notice warning">候选数量不足，请核对当前结果；不会补造商品或自动发起新请求。</p>}
    {candidates.length > 0 ? <div style={{ overflowX: 'auto' }}>
      <table data-testid="candidate-comparison">
        <caption>本次 Run 检索快照 · 不代表库存锁定或购买报价</caption>
        <thead><tr><th scope="col">商品</th><th scope="col">价格</th><th scope="col">可用库存</th>{attributes.map(key => <th scope="col" key={key}>{attributeLabels[key] ?? key}</th>)}<th scope="col">目录版本</th></tr></thead>
        <tbody>{candidates.map(item => <tr key={item.id} data-testid="candidate-row">
          <th scope="row">{text(item.data.name)}<br /><small>{item.id}</small></th>
          <td>{count(item.data.price_cents) === null ? 'UNKNOWN' : money(item.data.price_cents as number)}</td>
          <td>{count(item.data.available) ?? 'UNKNOWN'}</td>
          {attributes.map(key => <td key={key}>{text(item.attributes[key])}</td>)}
          <td>{count(item.data.catalog_version) ?? 'UNKNOWN'}</td>
        </tr>)}</tbody>
      </table>
    </div> : <p>尚无服务端候选快照。请查看运行状态与待补充需求。</p>}
    {run.result?.answer && <div data-testid="workflow-answer"><h3>工作流答复</h3><p style={{ whiteSpace: 'pre-wrap' }}>{run.result.answer}</p></div>}
    <small>以上来自本次 Run 的服务端约束与事实；业务状态以下方独立查询的资源为准。购买与退货提案分别确认。</small>
  </section>
}
