import { renderToStaticMarkup } from 'react-dom/server'
import { expect, it } from 'vitest'
import RecommendationResults from './RecommendationResults'
import type { Run } from '../api/agentWorkflow'

const run: Run = {
  id: 'run-1', thread_id: 'thread-1', request_id: 'request-1', status: 'COMPLETED',
  last_error: null, pending_confirmation: null, model_id: 'server-model', budget: {},
  constraints: { category: 'keyboard', max_price_cents: 50000, noise_preference: 'quiet',
    product_needs: { excluded_connections: ['双模', '三模'] },
    recommendation: { count: 3, compare_connections: true } },
  result: { answer: '服务端回答<script>不执行</script>', execution_mode: 'FIXTURE', error_codes: [], unfinished: [], citations: [],
    entity_refs: [{ kind: 'product', id: 'original', relation: 'original' },
      { kind: 'product', id: 'p1', relation: 'replacement' }, { kind: 'product', id: 'p1', relation: 'replacement' },
      { kind: 'product', id: 'p2', relation: 'replacement' }],
    facts: [
      { kind: 'product', id: 'original', data: { name: '原订单商品', price_cents: 9900 } },
      { kind: 'product', id: 'p1', data: { name: '有线键盘', price_cents: 19900, available: 0, attributes: { connection: '有线', noise: '静音', layout: '87键' }, catalog_version: 7 } },
      { kind: 'product', id: 'p2', data: { name: '无线键盘', price_cents: 29900, available: 8, attributes: { connection: '无线', connection_capabilities: ['wireless'], layout: '104键' }, catalog_version: 9 } },
      { kind: 'product', id: 'unreferenced', data: { name: '未引用商品', available: 20 } },
    ] },
}

it('compares only distinct replacement snapshots with requested count and explicit shortage', () => {
  const html = renderToStaticMarkup(<RecommendationResults run={run} />)
  for (const label of ['请求 3 款', '已核验候选 2 款', '候选数量不足', '500.00', '199.00', '299.00', '静音', '有线', '无线', '双模、三模', '连接方式对比', '可用库存', '检索快照']) expect(html).toContain(label)
  expect(html).toContain('<td>0</td>')
  expect(html).toContain('<td>8</td>')
  expect(html).not.toContain('原订单商品')
  expect(html).not.toContain('未引用商品')
  expect(html).not.toContain('批准并继续')
})

it('keeps unverified price and inventory unknown and reports missing snapshots separately', () => {
  const html = renderToStaticMarkup(<RecommendationResults run={{ ...run, result: { ...run.result!, facts: [
    { kind: 'product', id: 'p1', data: { name: '部分商品快照', price_cents: null, available: null, attributes: {} } },
  ] } }} />)
  expect(html).toContain('已核验候选 1 款')
  expect(html).toContain('1 款引用缺少商品快照')
  expect(html).toContain('<td>UNKNOWN</td>')
  expect(html).not.toContain('¥0.00')
})

it('renders the API answer safely without presenting it as a committed transaction', () => {
  const html = renderToStaticMarkup(<RecommendationResults run={run} />)
  expect(html).toContain('服务端回答&lt;script&gt;不执行&lt;/script&gt;')
  expect(html).not.toContain('<script>')
  expect(html).toContain('业务状态以下方独立查询的资源为准')
})

it('does not claim shortage when enough candidates are returned or no count was requested', () => {
  const html = renderToStaticMarkup(<RecommendationResults run={{ ...run, constraints: { recommendation: { count: 2 } } }} />)
  expect(html).toContain('请求 2 款')
  expect(html).not.toContain('候选数量不足')
  const unspecified = renderToStaticMarkup(<RecommendationResults run={{ ...run, constraints: {} }} />)
  expect(unspecified).toContain('请求数量未指定')
  expect(unspecified).not.toContain('请求 0 款')
})

it('shows the known constraints while the run has no product snapshot or final answer', () => {
  const html = renderToStaticMarkup(<RecommendationResults run={{ ...run, status: 'RUNNING', result: null }} />)
  expect(html).toContain('500.00')
  expect(html).toContain('尚无服务端候选快照')
  expect(html).not.toContain('候选数量不足')
  expect(html).not.toContain('服务端回答&lt;script&gt;')
})

it('shows selected preferences without listing the server null defaults as unknown requirements', () => {
  const html = renderToStaticMarkup(<RecommendationResults run={{ ...run, result: null, constraints: {
    product_needs: { layout: null, keyboard_type: null, connection: '无线', usage: null, excluded_connections: [] },
  } }} />)
  expect(html).toContain('连接方式：无线')
  expect(html).not.toContain('layout：UNKNOWN')
  expect(html).not.toContain('keyboard_type：UNKNOWN')
  expect(html).not.toContain('适用场景：UNKNOWN')
})
