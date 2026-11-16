/** CONTRACT_TEST_ONLY. SDK MockTransport; every business effect uses formal APIs. */
import { test, expect, type Page, type APIRequestContext } from '@playwright/test'
import { mkdir, writeFile } from 'node:fs/promises'
import { API_ORIGIN } from './environment'

const API = API_ORIGIN + '/api/v1'
const key = { 'X-E2E-Key': 'agentmall-local-e2e' }
const password = 'AgentMall-demo-2026!'
async function control(request: APIRequestContext, route: string, data?: object) {
  const r = data === undefined ? await request.get(API_ORIGIN + '/__test' + route, { headers: key })
    : await request.post(API_ORIGIN + '/__test' + route, { headers: key, data })
  expect(r.ok(), await r.text()).toBeTruthy()
  return r.json()
}
const facts = (request: APIRequestContext) => control(request, '/facts')
async function auth(request: APIRequestContext, login = 'buyer1') {
  const r = await request.post(API + '/auth/login', { data: { login, password } })
  expect(r.ok()).toBeTruthy()
  return { Authorization: 'Bearer ' + (await r.json()).access_token }
}
async function post(request: APIRequestContext, headers: Record<string, string>, route: string, data: object) {
  const r = await request.post(API + route, { headers: { ...headers, 'Idempotency-Key': crypto.randomUUID() }, data })
  expect(r.ok(), await r.text()).toBeTruthy()
  return r.json()
}
async function login(page: Page, restored = false) {
  if (restored) await page.getByRole('link', { name: '去登录' }).click()
  else await page.goto('/login')
  await page.getByLabel('账号', { exact: true }).fill('buyer1')
  await page.getByLabel('密码', { exact: true }).fill(password)
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await expect(page.getByRole('button', { name: '退出登录' })).toBeVisible()
}
async function start(page: Page, message: string, mode = 'multi') {
  await login(page)
  await page.locator('a[href="/agent/workspace"]').first().click()
  await page.getByLabel('运行模式').selectOption(mode)
  await page.getByRole('button', { name: '创建 Thread' }).click()
  await expect(page.getByTestId('thread-id')).toBeVisible()
  await page.getByLabel('本次任务').fill(message)
  await page.getByRole('button', { name: '启动新 Run' }).click()
  await expect(page.getByTestId('run-status')).toBeVisible()
  await expect(page.getByTestId('provider-mode')).toContainText('OFFLINE DEMO / MOCK MODEL')
}
async function delivered(request: APIRequestContext) {
  const buyer = await auth(request)
  const products = await (await request.get(API + '/products?category=keyboard', { headers: buyer })).json()
  let p = await post(request, buyer, '/checkout/proposals', { request_id: crypto.randomUUID(), proposal_slot: 'contract_setup', address_label: 'demo_dorm', items: [{ product_id: products.items[0].id, quantity: 1 }] })
  let c = await post(request, buyer, `/proposals/${p.proposal_id}/confirmations`, { decision: 'approve' })
  const receipt = await post(request, buyer, '/orders', { proposal_id: p.proposal_id, confirmation_id: c.confirmation_id })
  let order = await (await request.get(API + '/orders/' + receipt.order_id, { headers: buyer })).json()
  p = await post(request, buyer, `/orders/${order.id}/payment-proposals`, { request_id: crypto.randomUUID(), expected_version: order.version })
  c = await post(request, buyer, `/proposals/${p.proposal_id}/confirmations`, { decision: 'approve' })
  await post(request, buyer, `/orders/${order.id}/mock-payments`, { proposal_id: p.proposal_id, confirmation_id: c.confirmation_id })
  order = await (await request.get(API + '/orders/' + order.id, { headers: buyer })).json()
  const merchant = await auth(request, 'merchant')
  for (const step of ['ship', 'deliver']) order = await post(request, merchant, `/merchant/orders/${order.id}/${step}`, { expected_version: order.version })
  return order.id as string
}
const replace = (id: string) => `订单${id}质量问题，申请退货；然后推荐另一款500元以内静音键盘，准备购买一件，送演示宿舍。`
async function decide(page: Page, decision: 'approve' | 'reject') {
  const response = page.waitForResponse(r => r.request().method() === 'POST' && r.url().endsWith('/resume'))
  await page.getByRole('button', { name: decision === 'approve' ? '批准并继续工作流' : '拒绝并继续工作流' }).click()
  expect((await response).ok()).toBeTruthy()
}
test('V217 continuous A-B-C: independent decisions, refresh and real SQL stay consistent', async ({ page, request }) => {
  await control(request, '/reset', {})
  await page.route('**/*', r => new URL(r.request().url()).hostname === '127.0.0.1' ? r.continue() : r.abort())
  const originalOrder = await delivered(request)
  const setup = await facts(request)
  await control(request, '/sdk-mode', { program: 'context-catalog' })
  await start(page, '推荐三款400元以内支持无线连接的静音键盘，不要购买。', 'single')
  await expect(page.getByTestId('run-status')).toHaveText('COMPLETED')
  await expect(page.getByTestId('candidate-row')).toHaveCount(3)
  const recommendation = await facts(request)
  expect(recommendation.orders).toBe(setup.orders)
  expect(recommendation.confirmations).toBe(setup.confirmations)

  const started = page.waitForResponse(r => r.request().method() === 'POST' && r.url().endsWith('/runs'))
  await page.getByLabel('本次任务').fill('就买第二款，一件，送演示宿舍。')
  await page.getByRole('button', { name: '启动新 Run' }).click()
  expect((await started).ok()).toBeTruthy()
  await expect(page.getByRole('heading', { name: '确认购买快照' })).toBeVisible()
  const waitingPurchase = await facts(request)
  expect(waitingPurchase.orders).toBe(setup.orders)
  const buyer = await auth(request)
  const purchasePending = waitingPurchase.run_rows.at(-1).pending_confirmation
  const inspectedPurchase = await (await request.get(API + '/proposals/' + purchasePending.proposal_id, { headers: buyer })).json()
  expect(inspectedPurchase.action_type).toBe('CHECKOUT')
  expect(inspectedPurchase.status).toBe('PENDING')
  expect(inspectedPurchase.canonical_payload.items[0].quantity).toBe(1)
  await decide(page, 'approve') // Explicit synthetic operator action after actual inspection.
  await expect(page.getByTestId('run-status')).toHaveText('COMPLETED')
  const purchased = await facts(request)
  expect(purchased.orders).toBe(setup.orders + 1)
  const savedUrl = page.url()
  await page.reload()
  await login(page, true)
  await expect(page).toHaveURL(savedUrl)
  await expect(page.getByTestId('resource-order').filter({ hasText: 'PENDING_PAYMENT' })).toHaveCount(1)
  expect((await facts(request)).orders).toBe(purchased.orders)

  await control(request, '/sdk-mode', { program: 'return_replace', order_id: originalOrder })
  await page.locator('a[href="/agent/workspace"]').first().click()
  await page.getByLabel('运行模式').selectOption('multi')
  await page.getByRole('button', { name: '创建 Thread' }).click()
  await page.getByLabel('本次任务').fill(replace(originalOrder))
  await page.getByRole('button', { name: '启动新 Run' }).click()
  await expect(page.getByRole('heading', { name: '确认退货申请' })).toBeVisible()
  const beforeReturn = await facts(request)
  expect(beforeReturn.case_rows).toHaveLength(0)
  const returnPending = beforeReturn.run_rows.at(-1).pending_confirmation
  const inspectedReturn = await (await request.get(API + '/proposals/' + returnPending.proposal_id, { headers: buyer })).json()
  expect(inspectedReturn.action_type).toBe('RETURN_REQUEST')
  expect(inspectedReturn.status).toBe('PENDING')
  await decide(page, 'approve') // First independent Multi decision, never preapproves checkout.
  await expect(page.getByRole('heading', { name: '确认购买快照' })).toBeVisible()
  const middle = await facts(request)
  expect(middle.case_rows).toHaveLength(1)
  expect(middle.orders).toBe(purchased.orders)
  const checkoutPending = middle.run_rows.at(-1).pending_confirmation
  const inspectedCheckout = await (await request.get(API + '/proposals/' + checkoutPending.proposal_id, { headers: buyer })).json()
  expect(inspectedCheckout.action_type).toBe('CHECKOUT')
  expect(inspectedCheckout.status).toBe('PENDING')
  expect(inspectedCheckout.proposal_id).not.toBe(inspectedReturn.proposal_id)
  const firstConfirmation = middle.confirmation_rows.find((c: { proposal_id: string }) => c.proposal_id === returnPending.proposal_id)
  const stale = await request.post(API + `/agent/threads/${middle.run_rows.at(-1).thread_id}/resume`, {
    headers: buyer, data: { run_id: middle.run_rows.at(-1).id, interrupt_id: checkoutPending.interrupt_id,
      proposal_id: checkoutPending.proposal_id, confirmation_id: firstConfirmation.id, request_id: crypto.randomUUID() },
  })
  expect(stale.status()).toBe(409)
  expect((await facts(request)).orders).toBe(purchased.orders)
  await decide(page, 'approve') // Second explicit inspection and separate Confirmation/Resume.
  await expect(page.getByTestId('run-status')).toHaveText('COMPLETED')
  const result = await facts(request)
  expect(result.orders).toBe(setup.orders + 2)
  expect(result.case_rows).toHaveLength(1)
  expect(result.reserved).toBe(setup.reserved + 2)
  expect(result.payment_rows).toHaveLength(setup.payment_rows.length)
  expect(result.refund_rows).toHaveLength(0)
  expect(result.confirmations).toBe(setup.confirmations + 3)
  const multiConfirmations = result.confirmation_rows.filter((c: { proposal_id: string }) => [returnPending.proposal_id, checkoutPending.proposal_id].includes(c.proposal_id))
  expect(multiConfirmations).toHaveLength(2)
  expect(multiConfirmations.every((c: { consumed_at: string | null }) => c.consumed_at !== null)).toBe(true)
  expect(new Set(multiConfirmations.map((c: { id: string }) => c.id)).size).toBe(2)
  expect(result.checkpoint_rows).toBeGreaterThan(0)
  expect(result.provider_http_requests).toBe(0)
  expect(result.real_model_calls).toBe(0)
  expect(result.blocked_external_attempts).toBe(0)
  await mkdir('test-results/v217', { recursive: true })
  await writeFile('test-results/v217/continuous-api-sql.json', JSON.stringify({
    classification: 'CONTRACT_TEST_ONLY', source: 'SDK_MOCK_MODEL_REAL_API_POSTGRESQL',
    setup, recommendation, waitingPurchase, purchased, beforeReturn, middle, result,
    inspections: [inspectedPurchase, inspectedReturn, inspectedCheckout],
    stale_confirmation_http: stale.status(), synthetic_operator_decisions: 3,
  }, null, 2))
  await page.screenshot({ path: 'test-results/v217/continuous-completed.png', fullPage: true })
})
