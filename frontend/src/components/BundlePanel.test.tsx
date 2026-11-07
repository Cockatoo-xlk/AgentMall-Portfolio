import { renderToStaticMarkup } from 'react-dom/server'
import { expect, it, vi } from 'vitest'
import BundlePanel from './BundlePanel'
import { contextRunInput, type BundleOffer, type ThreadContext } from '../api/threadContext'

const bundle: BundleOffer = {
  bundle_id: 'bundle-1', name: '办公组合', thread_id: 'thread-1', source_run_id: 'run-1', context_version: 2,
  budget_cents: 500000, total_cents: 100000, remaining_cents: 400000, expires_at: '2099-01-01T00:00:00Z', valid: true, invalid_reason: null,
  items: [{ id: 'p1', rank: 1, name: '<script>合成显示器</script>', category: 'monitor', attributes: { screen_inches: '27' },
    price_cents: 100000, currency: 'CNY', catalog_version: 1, quantity: 1, quantity_source: 'ESTIMATE', subtotal_cents: 100000, available_snapshot: 10, reasons: ['真实检索结果'] }],
}
const context: ThreadContext = { version: 2, preferences: { bundle: { budget_cents: 500000, parts: [{ category: 'monitor' }, { category: 'keyboard' }] } }, bundles: [bundle], candidate_sets: [], provenance: {}, updated_at: null }
it('renders all bundle lines, budget, estimate and immutable source without business actions', () => {
  const choose = vi.fn()
  const html = renderToStaticMarkup(<BundlePanel context={context} busy={false} selected="" onSelect={choose} />)
  for (const label of ['5,000.00', '1,000.00', '4,000.00', '屏幕英寸', '27', '估算', 'run-1', 'bundle-1', '独立确认', '不保证全目录最优']) expect(html).toContain(label)
  expect(html).toContain('&lt;script&gt;')
  expect(html).not.toContain('<script>')
  expect(html).not.toContain('执行模拟付款')
  expect(choose).not.toHaveBeenCalled()
})
it('disables stale/expired bundles and exposes reason', () => {
  const html = renderToStaticMarkup(<BundlePanel context={{ ...context, bundles: [{ ...bundle, valid: false, invalid_reason: 'STALE_BUNDLE' }] }} busy={false} selected="" onSelect={vi.fn()} />)
  expect(html).toContain('disabled=""')
  expect(html).toContain('STALE_BUNDLE')
})
it('keeps required categories when no complete bundle fits', () => {
  const html = renderToStaticMarkup(<BundlePanel context={{ ...context, bundles: [], bundle_status: { status: 'NO_FEASIBLE_BUNDLE', reason: 'GLOBAL_BUDGET_INSUFFICIENT', missing_categories: [] } }} busy={false} selected="" onSelect={vi.fn()} />)
  expect(html).toContain('显示器、键盘')
  expect(html).toContain('总预算不足')
  expect(html).not.toContain('选择此整套方案')
})
it('passes only a selected bundle reference with original request identity', () => {
  expect(contextRunInput('r', '就买这套，每样一件，送演示宿舍', 2, undefined, 'b')).toEqual({ request_id: 'r', message: '就买这套，每样一件，送演示宿舍', expected_context_version: 2, bundle_id: 'b' })
  expect(contextRunInput('r', '推荐', 0)).not.toHaveProperty('bundle_id')
})
