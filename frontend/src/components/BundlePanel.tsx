import { useEffect, useState } from 'react'
import { money } from '../api/format'
import { categoryLabels, attributeLabels } from '../api/catalog'
import type { BundleOffer, ThreadContext } from '../api/threadContext'

function Offer({ bundle, busy, selected, onSelect }: { bundle: BundleOffer; busy: boolean; selected: string; onSelect: (id: string) => void }) {
  const [now, setNow] = useState(Date.now())
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [])
  const expired = Date.parse(bundle.expires_at) <= now
  const valid = bundle.valid && !expired
  return <article className="stack bundle-offer" data-testid="bundle-offer">
    <header><h3>{bundle.name}</h3><label><input type="radio" name="bundle" checked={selected === bundle.bundle_id}
      disabled={busy || !valid} onChange={() => onSelect(bundle.bundle_id)} />选择此整套方案</label></header>
    <p className={valid ? 'muted' : 'notice warning'}>{valid ? '当前商品事实已核验；推荐快照不是购买授权或有效报价。' : `方案已失效，需要重新检索：${expired ? '已到有效期' : bundle.invalid_reason}`}</p>
    <div className="resource-grid">{bundle.items.map(item => <section key={item.id} className="resource-card" data-testid="bundle-item">
      <small>{categoryLabels[item.category]} · Catalog v{item.catalog_version}</small>
      <h4>{item.rank}. {item.name}</h4>
      <dl className="bundle-specs">{Object.entries(item.attributes).slice(0, 8).map(([key, value]) => <div key={key}><dt>{attributeLabels[key] ?? key}</dt><dd>{value}</dd></div>)}</dl>
      <p>单价 {money(item.price_cents)} × {item.quantity}{item.quantity_source === 'ESTIMATE' ? '（估算，购买需明确数量）' : '（用户指定）'}</p>
      <strong>小计 {money(item.subtotal_cents)}</strong>
      <small>可用库存快照 {item.available_snapshot} · 商品 {item.id}</small>
      <ul>{item.reasons.map(reason => <li key={reason}>{reason}</li>)}</ul>
    </section>)}</div>
    <p className="bundle-total">整套 {money(bundle.total_cents)} · 总预算 {money(bundle.budget_cents)} · 剩余 {money(bundle.remaining_cents)}</p>
    <small>方案 {bundle.bundle_id} · 上下文 v{bundle.context_version} · 来源 Run {bundle.source_run_id}<br />服务端有效期 {new Date(bundle.expires_at).toLocaleString()}</small>
    <p className="muted">有界检索候选中按静音优先、总价、商品 ID 稳定排序；不保证全目录最优。购买前重新核对所有商品，任一变化都停止整套购买。</p>
    {selected === bundle.bundle_id && <button type="button" className="text-button" disabled={busy} onClick={() => onSelect('')}>取消方案选择</button>}
    <p>购买需在下方明确输入“就买这套，每样一件，送演示宿舍”，再独立确认完整订单快照。选择方案不会创建订单。</p>
  </article>
}
export default function BundlePanel({ context, busy, selected, onSelect }: { context: ThreadContext; busy: boolean; selected: string; onSelect: (id: string) => void }) {
  if (!context.preferences.bundle) return null
  return <section className="stack" aria-label="组合购物方案">
    <h2>组合购物方案 · 总预算 {money(context.preferences.bundle.budget_cents)}</h2>
    <p>必选品类：{context.preferences.bundle.parts.map(p => categoryLabels[p.category]).join('、')}</p>
    {context.bundle_status?.status === 'NO_FEASIBLE_BUNDLE' && <p role="status" className="notice warning">当前检索池没有完整可行方案：{context.bundle_status.reason}。缺少品类：{context.bundle_status.missing_categories?.map(c => categoryLabels[c]).join('、') || '总预算不足'}。保留全部需求，请明确调整后重新推荐。</p>}
    {(context.bundles ?? []).map(bundle => <Offer key={bundle.bundle_id} bundle={bundle} busy={busy} selected={selected} onSelect={onSelect} />)}
    {!context.bundles?.length && context.bundle_status?.status !== 'NO_FEASIBLE_BUNDLE' && <p>正在等待全部品类的真实检索和组合计算。</p>}
  </section>
}
