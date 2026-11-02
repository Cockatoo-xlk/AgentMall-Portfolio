import { useState } from 'react'
import type { ContextOperation, ThreadContext } from '../api/threadContext'
import { money } from '../api/format'

export default function ThreadMemory({ context, busy, selected, onSelect, onPatch }: {
  context: ThreadContext; busy: boolean; selected: string; onSelect: (id: string) => void
  onPatch: (operations: ContextOperation[]) => void
}) {
  const [budget, setBudget] = useState('')
  const p = context.preferences
  return <section className="panel stack" aria-label="会话偏好与候选">
    <h2>本 Thread 已确认偏好</h2>
    <small data-testid="context-version">上下文版本 {context.version} · 来源 {context.provenance.type ?? '尚未建立'} {context.provenance.run_id ?? ''}</small>
    <p data-testid="context-preferences">
      品类：{({ keyboard: '键盘', mouse: '鼠标', headphones: '耳机' } as Record<string, string>)[p.category ?? ''] ?? '未指定'} ·
      预算：{p.max_price_cents === undefined ? '未指定' : money(p.max_price_cents)} ·
      噪声：{p.noise_preference === 'quiet' ? '静音偏好' : '未指定'} ·
      连接：{p.product_needs?.connection ?? '未指定'}
    </p>
    <p className="muted">仅记住结构化偏好和已核验的商品引用；购买意图、数量、地址和授权不跨轮继承。</p>
    <div className="thread-preference-controls">
      <label>修改预算（元）<input type="number" min="0" max="1000000" step="0.01" value={budget} onChange={e => setBudget(e.target.value)} /></label>
      <button type="button" className="button secondary" disabled={busy || budget === '' || !Number.isFinite(Number(budget)) || Number(budget) < 0} onClick={() => onPatch([{ op: 'REPLACE', field: 'max_price_cents', value: Math.round(Number(budget) * 100) }])}>保存预算</button>
      <button type="button" className="text-button" disabled={busy} onClick={() => onPatch([{ op: 'CLEAR', field: 'max_price_cents' }])}>清除预算</button>
      <button type="button" className="text-button" disabled={busy} onClick={() => onPatch([{ op: 'CLEAR', field: 'connection' }])}>清除连接偏好</button>
    </div>
    {context.candidate_sets.map(set => <section key={set.id} data-testid="candidate-set" className="stack">
      <label><input type="radio" name="candidate-set" checked={selected === set.id} disabled={!set.valid || busy} onChange={() => onSelect(set.id)} />引用此名单 · 来源 Run {set.run_id}</label>
      <small>名单 {set.id} · {set.valid ? '商品状态已核验；此名单不是购买报价' : '历史候选已变化，需要重新检索'}</small>
      <div className="resource-grid">{set.items.map(item => <article className="resource-card" data-testid="numbered-candidate" key={item.id}>
        <h3>{item.rank}. {item.name}</h3><p>{money(item.price_cents)}</p>
        <small>商品 {item.id} · Catalog v{item.catalog_version}</small>
      </article>)}</div>
    </section>)}
    {!context.candidate_sets.length && <p>暂无当前有效候选名单。偏好变化后请重新检索，再按编号选择。</p>}
  </section>
}
