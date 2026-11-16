import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { expect, it } from 'vitest'
import { BusinessResourceDetails } from './WorkflowResources'

it('shows independently queried order lines and pending payment without declaring payment', () => {
  const html = renderToStaticMarkup(<MemoryRouter><BusinessResourceDetails reference={{ kind: 'order', id: 'order-1' }} data={{
    id: 'order-1', status: 'PENDING_PAYMENT', total_cents: 39800, address_label: 'demo_dorm', policy_version: 'policy-v1',
    items: [{ product_id: 'p1', name_snapshot: '静音键盘', unit_price_cents: 19900, quantity: 2, attributes_snapshot: {} }],
  }} /></MemoryRouter>)
  for (const label of ['PENDING_PAYMENT', '398.00', '静音键盘', '× 2', '演示宿舍地址', '尚未付款', '/orders/order-1']) expect(html).toContain(label)
  expect(html).not.toContain('已支付')
})

it('keeps current product stock zero visible and never changes missing stock to zero', () => {
  const product = { id: 'p1', name: '当前商品', price_cents: 19900, available: 0, attributes: { connection: '有线' }, catalog_version: 8 }
  const html = renderToStaticMarkup(<MemoryRouter><BusinessResourceDetails reference={{ kind: 'product', id: 'p1' }} data={product} /></MemoryRouter>)
  expect(html).toContain('当前可用库存：0')
  expect(html).toContain('有线')
  expect(html).toContain('目录版本 8')
  const unknown = renderToStaticMarkup(<MemoryRouter><BusinessResourceDetails reference={{ kind: 'product', id: 'p1' }} data={{ id: 'p1', name: '部分数据' }} /></MemoryRouter>)
  expect(unknown).toContain('当前可用库存：UNKNOWN')
})

it('keeps requested return independent from refund and identifies the original business reference', () => {
  const html = renderToStaticMarkup(<MemoryRouter><BusinessResourceDetails reference={{ kind: 'case', id: 'case-1', relation: 'original' }} data={{ id: 'case-1', status: 'REQUESTED', order_id: 'order-original', reason_code: 'QUALITY_ISSUE' }} /></MemoryRouter>)
  for (const label of ['原业务引用', 'order-original', 'QUALITY_ISSUE', '尚未退款']) expect(html).toContain(label)
  expect(html).not.toContain('已退款')
})
