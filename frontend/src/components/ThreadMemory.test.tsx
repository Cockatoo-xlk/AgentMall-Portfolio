import { renderToStaticMarkup } from 'react-dom/server'
import { expect, it, vi } from 'vitest'
import ThreadMemory from './ThreadMemory'

it('shows server ranks without reranking stale candidates and never renders HTML', () => {
  const select = vi.fn()
  const html = renderToStaticMarkup(<ThreadMemory busy={false} selected="list-1" onSelect={select} onPatch={vi.fn()} context={{
    version: 8, preferences: { category: 'keyboard', max_price_cents: 40000, product_needs: { connection: '无线' } },
    provenance: { type: 'RUN', run_id: 'run-1' }, updated_at: null,
    candidate_sets: [{ id: 'list-1', run_id: 'run-1', valid: false, items: [
      { rank: 1, id: 'p1', name: '<script>secret()</script>', price_cents: 10000, currency: 'CNY', catalog_version: 1 },
      { rank: 2, id: 'p2', name: '合成键盘', price_cents: 20000, currency: 'CNY', catalog_version: 2 },
    ] }],
  }} />)
  expect(html).toContain('上下文版本 8')
  expect(html).toContain('2. 合成键盘')
  expect(html).toContain('&lt;script&gt;')
  expect(html).not.toContain('<script>')
  expect(html).toContain('需要重新检索')
  expect(html).toContain('disabled=""')
})

it('shows explicit excluded connection labels independently from wireless capability', () => {
  const html = renderToStaticMarkup(<ThreadMemory busy={false} selected="" onSelect={vi.fn()} onPatch={vi.fn()} context={{
    version: 3, preferences: { product_needs: { connection: '无线', excluded_connections: ['双模', '三模'] } },
    provenance: {}, updated_at: null, candidate_sets: [],
  }} />)
  expect(html).toContain('排除连接标签：双模、三模')
  expect(html).toContain('清除连接排除')
})

it('shows expanded category constraints with explicit clear actions', () => {
  const html = renderToStaticMarkup(<ThreadMemory busy={false} selected="" onSelect={vi.fn()} onPatch={vi.fn()} context={{
    version: 2, preferences: { category: 'monitor', product_needs: { screen_inches: '27' } },
    provenance: {}, updated_at: null, candidate_sets: [],
  }} />)
  expect(html).toContain('显示器')
  expect(html).toContain('27')
  expect(html).toContain('清除屏幕尺寸')
})
