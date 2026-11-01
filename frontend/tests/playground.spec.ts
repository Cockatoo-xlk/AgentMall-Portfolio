import { test, expect } from '@playwright/test'
import type { Page, APIRequestContext } from '@playwright/test'
import { mkdir, writeFile } from 'node:fs/promises'
import path from 'node:path'
import { API_ORIGIN } from './environment'
import type { Run, RunEvent } from '../src/api/agentWorkflow'
import type { ProviderRuntime } from '../src/api/providerRuntime'

const key = { 'X-E2E-Key': 'agentmall-local-e2e' }
const password = 'AgentMall-demo-2026!'
const evidence = path.resolve(process.env.AGENTMALL_PLAYGROUND_EVIDENCE_DIR ?? 'test-results/playground')
interface Facts {
  orders: number
  checkpoint_rows: number
  real_model_calls: number
  provider_http_requests: number
  blocked_external_attempts: number
  run_rows: Run[]
  run_event_rows: RunEvent[]
  order_rows: { id: string; status: string }[]
  confirmation_rows: { id: string; proposal_id: string; decision: string }[]
  payment_rows: { status: string }[]
  case_rows: { status: string }[]
  refund_rows: unknown[]
  sdk: (ProviderRuntime & { wire_requests: number }) | null
}
async function control(request: APIRequestContext, route: string, data?: object) {
  const r = data === undefined
    ? await request.get(API_ORIGIN + '/__test' + route, { headers: key })
    : await request.post(API_ORIGIN + '/__test' + route, { headers: key, data })
  expect(r.ok(), await r.text()).toBeTruthy()
  return r.json()
}
const facts = (r: APIRequestContext): Promise<Facts> => control(r, '/facts')
async function login(page: Page, current = false) {
  if (current) await page.getByRole('link', { name: '去登录' }).click()
  else await page.goto('/login')
  await page.getByLabel('账号', { exact: true }).fill('buyer1')
  await page.getByLabel('密码', { exact: true }).fill(password)
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await expect(page.getByRole('button', { name: '退出登录' })).toBeVisible()
}
async function workspace(page: Page, message: string, mode = 'multi') {
  await login(page)
  await page.locator('a[href="/agent/workspace"]').first().click()
  await page.getByLabel('运行模式').selectOption(mode)
  await page.getByRole('button', { name: '创建 Thread' }).click()
  await expect(page.getByTestId('thread-id')).toBeVisible()
  await page.getByLabel('本次任务').fill(message)
  await page.getByRole('button', { name: '启动新 Run' }).click()
  await expect(page.getByTestId('run-status')).toBeVisible()
}
async function capture(page: Page, request: APIRequestContext, name: string) {
  await mkdir(evidence, { recursive: true })
  await writeFile(path.join(evidence, name + '.json'), JSON.stringify(await facts(request), null, 2))
  await page.screenshot({ path: path.join(evidence, name + '.png'), fullPage: true, animations: 'disabled' })
}
async function deliveredOrder(request: APIRequestContext) {
  async function auth(user: string) {
    const r = await request.post(API_ORIGIN + '/api/v1/auth/login', { data: { login: user, password } })
    expect(r.ok()).toBeTruthy()
    return { Authorization: `Bearer ${(await r.json()).access_token}` }
  }
  const buyer = await auth('buyer1')
  const merchant = await auth('merchant')
  async function post(route: string, data: object, headers = buyer) {
    const r = await request.post(API_ORIGIN + '/api/v1' + route, { headers: { ...headers, 'Idempotency-Key': crypto.randomUUID() }, data })
    expect(r.ok(), await r.text()).toBeTruthy()
    return r.json()
  }
  async function get(route: string) {
    const r = await request.get(API_ORIGIN + '/api/v1' + route, { headers: buyer })
    expect(r.ok()).toBeTruthy()
    return r.json()
  }
  const product = (await get('/products?category=keyboard')).items[0].id
  let p = await post('/checkout/proposals', { request_id: crypto.randomUUID(), proposal_slot: 'synthetic_setup', address_label: 'demo_dorm', items: [{ product_id: product, quantity: 1 }] })
  let c = await post(`/proposals/${p.proposal_id}/confirmations`, { decision: 'approve' })
  const receipt = await post('/orders', { proposal_id: p.proposal_id, confirmation_id: c.confirmation_id })
  let order = await get('/orders/' + receipt.order_id)
  p = await post(`/orders/${order.id}/payment-proposals`, { request_id: crypto.randomUUID(), expected_version: order.version })
  c = await post(`/proposals/${p.proposal_id}/confirmations`, { decision: 'approve' })
  await post(`/orders/${order.id}/mock-payments`, { proposal_id: p.proposal_id, confirmation_id: c.confirmation_id })
  order = await get('/orders/' + order.id)
  for (const event of ['ship', 'deliver'])
    order = await post(`/merchant/orders/${order.id}/${event}`, { expected_version: order.version }, merchant)
  expect(order.status).toBe('DELIVERED')
  return order.id as string
}
test.beforeEach(async ({ page, request }) => {
  await control(request, '/reset', {})
  await page.route('**/*', r => new URL(r.request().url()).hostname === '127.0.0.1' ? r.continue() : r.abort())
})
test.afterEach(async ({ request }, testInfo) => {
  const f = await facts(request)
  await mkdir(path.join(evidence, 'final-states'), { recursive: true })
  await writeFile(path.join(evidence, 'final-states', testInfo.title.replace(/[^a-zA-Z0-9]+/g, '-') + '.json'), JSON.stringify({ status: testInfo.status, facts: f }, null, 2))
  expect(f.real_model_calls).toBe(0)
  expect(f.provider_http_requests).toBe(0)
  expect(f.blocked_external_attempts).toBe(0)
  if (f.sdk) {
    expect(f.sdk.mode).toBe('MOCK_TRANSPORT')
    expect(f.sdk.requests_reserved).toBe(f.sdk.wire_requests)
    expect(f.sdk.actual_bill_cny).toBe('UNKNOWN')
  }
})
test('playground: server Fixture and disabled identities override frontend assumptions', async ({ page, request }) => {
  await login(page)
  await page.locator('a[href="/agent/workspace"]').first().click()
  await expect(page.getByTestId('provider-mode')).toContainText('Fixture')
  await control(request, '/workflow-mode', { mode: 'disabled' })
  await page.reload()
  await login(page, true)
  await expect(page.getByTestId('provider-mode')).toContainText('MODEL_DISABLED')
})
for (const [program, message, tool, mode] of [
  ['recommend', '请推荐300元以内的静音键盘，不购买', 'retrieve_products', 'multi'],
  ['orders', '查询我本人的订单状态，不购买', 'list_orders', 'multi'],
  ['orders', '只查看本人的订单', 'list_orders', 'single'],
]) test(`playground: ${mode} SDK ${program} chooses real tools from mock wire output`, async ({ page, request }) => {
  await control(request, '/sdk-mode', { program })
  await workspace(page, message, mode)
  await expect(page.getByTestId('run-status')).toHaveText('COMPLETED')
  await expect(page.getByTestId('provider-mode')).toContainText('MockTransport')
  const f = await facts(request)
  expect(f.orders).toBe(0)
  expect(f.sdk!.valid_responses).toBeGreaterThanOrEqual(2)
  expect(f.run_event_rows.some(e => e.event_type === 'tool' && e.payload_summary.name === tool)).toBe(true)
  expect(f.checkpoint_rows).toBeGreaterThan(0)
  await capture(page, request, `${mode}-${program}`)
})
test('playground: SDK purchase, lost Resume response, refresh and separate mock payment', async ({ page, request }) => {
  await control(request, '/sdk-mode', { program: 'purchase' })
  await workspace(page, '帮我找一款300元以内静音键盘准备购买，送演示宿舍')
  await expect(page.getByTestId('run-status')).toHaveText('WAITING_INPUT')
  expect((await facts(request)).orders).toBe(0)
  const reference = page.url()
  await capture(page, request, 'purchase-waiting')
  let dropped = false
  await page.route('**/agent/threads/*/resume', async route => {
    if (dropped) return route.continue()
    dropped = true
    await route.fetch()
    await route.abort('timedout')
  })
  await page.getByRole('button', { name: '批准并继续工作流' }).click()
  await expect(page.getByTestId('run-status')).toHaveText('COMPLETED')
  expect(dropped).toBe(true)
  const before = await facts(request)
  expect(before.orders).toBe(1)
  expect(before.confirmation_rows).toHaveLength(1)
  expect(before.payment_rows).toHaveLength(0)
  await page.reload()
  await login(page, true)
  await expect(page).toHaveURL(reference)
  await expect(page.getByTestId('run-status')).toHaveText('COMPLETED')
  await expect(page.getByTestId('provider-mode')).toContainText('MockTransport')
  expect((await facts(request)).sdk!.wire_requests).toBe(before.sdk!.wire_requests)
  await expect(page.getByTestId('run-event')).toHaveCount(before.run_event_rows.length)
  await capture(page, request, 'purchase-restored')
  await page.getByTestId('resource-order').getByRole('link', { name: '查看真实订单' }).click()
  await page.getByRole('button', { name: '模拟付款', exact: true }).click()
  await page.getByRole('button', { name: '批准并模拟付款', exact: true }).click()
  await expect(page.getByTestId('payment-receipt')).toContainText('SUCCEEDED')
  const final = await facts(request)
  expect(final.order_rows[0].status).toBe('PAID')
  expect(final.payment_rows).toEqual([expect.objectContaining({ status: 'SUCCEEDED' })])
  expect(new Set(final.confirmation_rows.map(c => c.proposal_id)).size).toBe(2)
  expect(final.sdk!.wire_requests).toBe(before.sdk!.wire_requests)
  await capture(page, request, 'separate-payment')
})
for (const program of ['timeout', 'missing_usage', 'malicious'])
  test(`playground: ${program} safely halts without approval, business writes or paid retries`, async ({ page, request }) => {
    await control(request, '/sdk-mode', { program })
    await workspace(page, '查询订单并准备购买')
    await expect(page.getByTestId('run-status')).toHaveText('PARTIAL')
    await expect(page.getByTestId('provider-panel')).toContainText('UNKNOWN')
    await expect(page.getByTestId('provider-panel')).toContainText('已安全停止')
    const f = await facts(request)
    expect(f.sdk!.wire_requests).toBe(1)
    expect(f.sdk!.valid_responses).toBe(0)
    expect(f.orders).toBe(0)
    expect(f.confirmation_rows).toHaveLength(0)
    await page.reload()
    await login(page, true)
    await expect(page.getByTestId('run-status')).toHaveText('PARTIAL')
    expect((await facts(request)).sdk!.wire_requests).toBe(1)
    await capture(page, request, program)
  })

test('playground: mobile SDK return and replacement keep two independent confirmations', async ({ page, request }) => {
  const order = await deliveredOrder(request)
  await control(request, '/sdk-mode', { program: 'return_replace', order_id: order })
  await page.setViewportSize({ width: 420, height: 900 })
  await workspace(page, `订单${order}有质量问题，想退掉，再帮我推荐一款500元以内静音键盘准备购买，送演示宿舍`)
  await expect(page.getByRole('heading', { name: '确认退货申请' })).toBeVisible()
  const first = await facts(request)
  const firstProposal = first.run_rows[0].pending_confirmation!.proposal_id
  expect(first.case_rows).toHaveLength(0)
  await page.getByRole('button', { name: '批准并继续工作流' }).click()
  await expect(page.getByRole('heading', { name: '确认购买快照' })).toBeVisible()
  const second = await facts(request)
  expect(second.run_rows[0].pending_confirmation!.proposal_id).not.toBe(firstProposal)
  expect(second.case_rows).toEqual([expect.objectContaining({ status: 'REQUESTED' })])
  expect(second.orders).toBe(1)
  await page.getByRole('button', { name: '批准并继续工作流' }).click()
  await expect(page.getByTestId('run-status')).toHaveText('COMPLETED')
  const final = await facts(request)
  expect(final.orders).toBe(2)
  expect(final.case_rows[0].status).toBe('REQUESTED')
  expect(final.refund_rows).toHaveLength(0)
  expect(final.confirmation_rows).toHaveLength(4) // setup checkout/payment plus return/replacement
  expect(new Set(final.confirmation_rows.map(c => c.proposal_id)).size).toBe(4)
  await expect(page.getByTestId('provider-mode')).toContainText('MockTransport')
  await capture(page, request, 'return-replacement-mobile')
})

test('playground: model cannot invent missing user quantity to create checkout', async ({ page, request }) => {
  await control(request, '/sdk-mode', { program: 'purchase' })
  await workspace(page, '帮我找300元以内静音键盘准备购买，送演示宿舍')
  await expect(page.getByTestId('run-status')).toHaveText('PARTIAL')
  const f = await facts(request)
  expect(f.orders).toBe(0)
  expect(f.confirmation_rows).toHaveLength(0)
  expect(f.run_event_rows.some(e => e.event_type === 'tool' && e.payload_summary.error_code === 'PURCHASE_DETAILS_REQUIRED')).toBe(true)
  await capture(page, request, 'missing-quantity-refused')
})
