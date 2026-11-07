import { useEffect, useState } from 'react'
import { money } from '../api/format'
import { categoryLabels, attributeLabels } from '../api/catalog'
import type { BundleOffer, BundleRevisionResult, ThreadContext } from '../api/threadContext'

const changeLabels: Record<string, string> = { KEPT: '保留', REPLACED: '替换', ADDED: '新增', REMOVED: '删除', UNRESOLVED: '未解决' }
const reasons: Record<string, string> = { CATEGORY_ADDED: '新增品类', STRICTLY_CHEAPER_REPLACEMENT: '严格低于原单价', REPLACE_REQUESTED: '用户要求替换', CONSTRAINT_CHANGED: '规格要求变化', CURRENT_SKU_REVALIDATION: '重读原SKU当前价格、版本和库存' }
function Changes({ diff }: { diff?: BundleRevisionResult | null }) {
  if (!diff) return null
  return <section className="stack" aria-label="修改前后对比" data-testid="bundle-diff">
    <h4>修改前后对比</h4>
    <p>原方案 {money(diff.old_total_cents)} · 新方案总价：{diff.new_total_cents === null ? '未知（无完整方案）' : money(diff.new_total_cents)}</p>
    <p>预算 {money(diff.old_budget_cents)} → {money(diff.new_budget_cents)} · 总额变化 {diff.delta_cents === null ? '未知' : money(diff.delta_cents)}</p>
    <div className="resource-grid">{diff.changes.map(change => <div className="resource-card" key={change.category}>
      <strong>{categoryLabels[change.category]}：{changeLabels[change.status] ?? '待核对'}</strong>
      <p>{change.old_item?.name ?? '原方案无此品类'} → {change.new_item?.name ?? (change.status === 'REMOVED' ? '已删除' : '当前无有效商品')}</p>
      <p>单价 {change.old_item ? money(change.old_item.price_cents) : '无'} → {change.new_item ? money(change.new_item.price_cents) : '未知'} · 数量 {change.old_item?.quantity ?? '无'} → {change.new_item?.quantity ?? '无'}</p>
      <small>{change.retrieval === 'REFRESHED' ? '重新检索' : change.status === 'REMOVED' ? '不再检索' : '复用并重新核验'} · {reasons[change.reason] ?? '重新核对需求'}</small>
      <p>小计变化：{change.delta_cents === null ? '未知' : money(change.delta_cents)}</p>
    </div>)}</div>
    <small>来源方案 {diff.source_bundle_id}；旧快照保持不变，不继承购买授权。</small>
  </section>
}

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
    <Changes diff={bundle.revision} />
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
    <p className="muted">在下方任务框修改：显示器不要换、耳机换个便宜的、键盘必须支持无线连接、再加一个音箱、不要鼠标了、总预算提高到6000元，或显示器一台、耳机两副。修改只重规划，不创建购买提案；不支持的硬约束需要澄清。</p>
    {context.bundle_status?.status === 'NO_FEASIBLE_BUNDLE' && <Changes diff={context.bundle_status.revision} />}
    {!!context.bundle_history?.length && <details><summary>历史方案（{context.bundle_history.length}，只读，不可购买）</summary>{context.bundle_history.map(old => <article className="stack" key={old.bundle_id}>
      <p>历史方案 {old.bundle_id} · 原总价 {money(old.total_cents)} · 来源 Run {old.source_run_id}</p>
      <p>{old.items.map(item => `${categoryLabels[item.category]}：${item.name} × ${item.quantity}`).join('；')}</p>
      <Changes diff={old.revision} />
    </article>)}</details>}
    {(context.bundles ?? []).map(bundle => <Offer key={bundle.bundle_id} bundle={bundle} busy={busy} selected={selected} onSelect={onSelect} />)}
    {!context.bundles?.length && context.bundle_status?.status !== 'NO_FEASIBLE_BUNDLE' && <p>正在等待全部品类的真实检索和组合计算。</p>}
  </section>
}
