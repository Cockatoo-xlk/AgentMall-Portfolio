import { test, expect } from '@playwright/test'
import type { APIRequestContext, Page } from '@playwright/test'
import { mkdir, writeFile } from 'node:fs/promises'
import path from 'node:path'
import type { ActionReceipt, MockPaymentReceipt, Order } from '../src/api/types'
const API = 'http://127.0.0.1:8001/api/v1'
const controlKey = { 'X-E2E-Key': 'agentmall-local-e2e' }
const password = 'AgentMall-demo-2026!'
const evidence = path.resolve(process.env.AGENTMALL_PAYMENT_EVIDENCE_DIR ?? 'test-results/payment')
interface Facts {
  orders: number
  reserved: number
  receipts: number
  events: number
  provider_http_requests: number
  real_model_calls: number
  blocked_external_attempts: number
  order_rows: Order[]
  payment_rows: {
    id: string
    order_id: string
    status: string
    amount_cents: number
    action_id: string
  }[]
  proposal_rows: {
    id: string
    action_type: string
    origin_request_id: string
    status: string
    canonical_payload: { order_id?: string; expected_version?: number }
  }[]
  confirmation_rows: {
    id: string
    proposal_id: string
    decision: string
    consumed_at: string | null
  }[]
  receipt_rows: { action_id: string; result: ActionReceipt }[]
  event_rows: { event_type: string; aggregate_id: string }[]
  product_rows: { id: string; on_hand: number; reserved: number }[]
}
async function control(
  request: APIRequestContext,
  endpoint: string,
  data?: object,
): Promise<Facts> {
  const r =
    data === undefined
      ? await request.get('http://127.0.0.1:8001/__test' + endpoint, {
          headers: controlKey,
        })
      : await request.post('http://127.0.0.1:8001/__test' + endpoint, {
          headers: controlKey,
          data,
        })
  expect(r.ok(), await r.text()).toBeTruthy()
  return r.json()
}
async function login(page: Page, user = 'buyer1', current = false) {
  if (current) await page.getByRole('link', { name: '去登录' }).click()
  else await page.goto('/login')
  await page.getByLabel('账号', { exact: true }).fill(user)
  await page.getByLabel('密码', { exact: true }).fill(password)
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await expect(page.getByRole('button', { name: '退出登录' })).toBeVisible()
}
async function cartOrder(page: Page) {
  await login(page)
  await page.locator('a[href="/"]').first().click()
  await page
    .getByTestId('product-card')
    .first()
    .getByRole('button', { name: '加入购物车', exact: true })
    .click()
  await page.locator('a[href="/cart"]').first().click()
  await page.getByRole('button', { name: '生成购买提案' }).click()
  await expect(page).toHaveURL(/\/proposals\//)
  await page.getByRole('button', { name: '确认并创建订单' }).click()
  await expect(page).toHaveURL(/\/orders\//)
  return page.url().split('/orders/')[1]
}
async function quote(page: Page) {
  await page.getByRole('button', { name: '模拟付款', exact: true }).click()
  await expect(page.getByRole('heading', { name: '请确认模拟付款', exact: true })).toBeVisible()
  return page.getByTestId('payment-proposal-id').innerText()
}
async function capture(page: Page, request: APIRequestContext, name: string) {
  await mkdir(evidence, { recursive: true })
  const f = await control(request, '/facts')
  await writeFile(path.join(evidence, name + '.json'), JSON.stringify(f, null, 2))
  await page.evaluate(() => window.scrollTo(0, 0))
  await page.screenshot({
    path: path.join(evidence, name + '.png'),
    fullPage: true,
    animations: 'disabled',
  })
}
function checkPaid(f: Facts, orderId: string) {
  expect(f.orders).toBe(1)
  expect(f.order_rows.find((o) => o.id === orderId)?.status).toBe('PAID')
  expect(f.payment_rows).toHaveLength(1)
  expect(f.payment_rows[0]).toMatchObject({
    order_id: orderId,
    status: 'SUCCEEDED',
  })
  expect(f.confirmation_rows).toHaveLength(2)
  expect(new Set(f.confirmation_rows.map((c) => c.proposal_id)).size).toBe(2)
  expect(f.proposal_rows.filter((p) => p.action_type === 'MOCK_PAYMENT')).toHaveLength(1)
  const p = f.proposal_rows.find((p) => p.action_type === 'MOCK_PAYMENT')!
  expect(p.status).toBe('EXECUTED')
  expect(f.payment_rows[0].action_id).toBe(p.id)
  expect(f.receipt_rows.filter((r) => r.action_id === p.id)).toHaveLength(1)
  expect(
    (f.receipt_rows.find((r) => r.action_id === p.id)!.result as MockPaymentReceipt).status,
  ).toBe('SUCCEEDED')
  expect(f.event_rows.filter((e) => e.event_type === 'ORDER_PAID')).toHaveLength(1)
  expect(f.reserved).toBe(0)
}
test.beforeEach(async ({ page, request }) => {
  await control(request, '/reset', {})
  await page.route('**/*', (r) =>
    new URL(r.request().url()).hostname === '127.0.0.1' ? r.continue() : r.abort(),
  )
})
test.afterEach(async ({ request }) => {
  const f = await control(request, '/facts')
  expect(f.provider_http_requests).toBe(0)
  expect(f.real_model_calls).toBe(0)
  expect(f.blocked_external_attempts).toBe(0)
})
test('payment: cart checkout to separate payment confirmation and real SQL receipt', async ({
  page,
  request,
}) => {
  const orderId = await cartOrder(page)
  const before = await control(request, '/facts')
  const reserved = before.product_rows.find((p) => p.reserved === 1)!
  await expect(page.getByText('不发生真实扣款', { exact: false })).toBeVisible()
  const proposalId = await quote(page)
  await expect(page.getByTestId('payment-snapshot')).toContainText(orderId)
  await expect(page.getByTestId('payment-snapshot')).toContainText('CNY')
  expect((await control(request, '/facts')).payment_rows).toHaveLength(0)
  await capture(page, request, 'payment-confirmation')
  await page.getByRole('button', { name: '批准并模拟付款', exact: true }).dblclick()
  await expect(page.getByRole('heading', { name: '模拟支付成功', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '模拟付款', exact: true })).toHaveCount(0)
  const after = await control(request, '/facts')
  checkPaid(after, orderId)
  expect(after.product_rows.find((p) => p.id === reserved.id)?.on_hand).toBe(reserved.on_hand - 1)
  expect(after.payment_rows[0].action_id).toBe(proposalId)
  await capture(page, request, 'payment-succeeded')
})

async function auth(request: APIRequestContext, loginName = 'buyer1') {
  const r = await request.post(API + '/auth/login', { data: { login: loginName, password } })
  expect(r.ok()).toBeTruthy()
  return { Authorization: `Bearer ${(await r.json()).access_token}` }
}
async function post(
  request: APIRequestContext,
  endpoint: string,
  data: object,
  headers: Record<string, string>,
) {
  const r = await request.post(API + endpoint, {
    headers: { ...headers, 'Idempotency-Key': crypto.randomUUID() },
    data,
  })
  expect(r.ok(), await r.text()).toBeTruthy()
  return r.json()
}
async function pendingOrder(page: Page, request: APIRequestContext) {
  const headers = await auth(request)
  const products = await (await request.get(API + '/products', { headers })).json()
  const p = await post(
    request,
    '/checkout/proposals',
    {
      request_id: crypto.randomUUID(),
      proposal_slot: 'payment_fixture',
      address_label: 'demo_dorm',
      items: [{ product_id: products.items[0].id, quantity: 1 }],
    },
    headers,
  )
  const c = await post(
    request,
    `/proposals/${p.proposal_id}/confirmations`,
    { decision: 'approve' },
    headers,
  )
  const receipt = await post(
    request,
    '/orders',
    { proposal_id: p.proposal_id, confirmation_id: c.confirmation_id },
    headers,
  )
  await login(page)
  await page.locator('a[href="/orders"]').first().click()
  await page.locator(`a[href="/orders/${receipt.order_id}"]`).click()
  return receipt.order_id as string
}
test('payment: DECLINED keeps reservation and never becomes a paid order', async ({
  page,
  request,
}) => {
  const id = await pendingOrder(page, request)
  await control(request, '/payment-mode', { result: 'DECLINED' })
  const before = await control(request, '/facts')
  await quote(page)
  await page.getByRole('button', { name: '批准并模拟付款', exact: true }).click()
  await expect(page.getByRole('heading', { name: '模拟支付已拒付', exact: true })).toBeVisible()
  const f = await control(request, '/facts')
  expect(f.order_rows.find((o) => o.id === id)?.status).toBe('PENDING_PAYMENT')
  expect(f.payment_rows).toHaveLength(0)
  expect(f.reserved).toBe(1)
  expect(f.product_rows).toEqual(before.product_rows)
  expect(f.event_rows.filter((e) => e.event_type === 'PAYMENT_DECLINED')).toHaveLength(1)
  expect(f.confirmation_rows.filter((c) => c.consumed_at !== null)).toHaveLength(2)
  expect(f.receipt_rows.some((r) => (r.result as MockPaymentReceipt).status === 'DECLINED')).toBe(
    true,
  )
  await capture(page, request, 'payment-declined')
})
test('payment: reject payment proposal never calls mock-payments', async ({ page, request }) => {
  await pendingOrder(page, request)
  await quote(page)
  let payments = 0
  page.on('request', (r) => {
    if (r.method() === 'POST' && r.url().endsWith('/mock-payments')) payments++
  })
  await page.getByRole('button', { name: '拒绝本次付款', exact: true }).click()
  await expect(page.getByRole('heading', { name: '支付提案已拒绝', exact: true })).toBeVisible()
  const f = await control(request, '/facts')
  expect(payments).toBe(0)
  expect(f.payment_rows).toHaveLength(0)
  expect(f.reserved).toBe(1)
  expect(f.proposal_rows.find((p) => p.action_type === 'MOCK_PAYMENT')?.status).toBe('REJECTED')
  expect(f.confirmation_rows.find((c) => c.decision === 'reject')?.consumed_at).toBeNull()
  expect(f.order_rows[0].status).toBe('PENDING_PAYMENT')
})
test('payment: order expires on the database clock before execution, releases stock once', async ({
  page,
  request,
}) => {
  const id = await pendingOrder(page, request)
  const before = await control(request, '/facts')
  await control(request, '/order-condition', { order_id: id, condition: 'near_expiry' })
  await quote(page)
  await page.route(
    '**/mock-payments',
    async (route) => {
      await control(request, '/order-condition', { order_id: id, condition: 'expire' })
      await route.continue()
    },
    { times: 1 },
  )
  await page.getByRole('button', { name: '批准并模拟付款', exact: true }).click()
  await expect(page.getByRole('heading', { name: '模拟支付已过期', exact: true })).toBeVisible()
  const f = await control(request, '/facts')
  expect(f.order_rows[0].status).toBe('EXPIRED')
  expect(f.payment_rows).toHaveLength(0)
  expect(f.reserved).toBe(0)
  expect(f.product_rows.reduce((n, p) => n + p.on_hand, 0)).toBe(
    before.product_rows.reduce((n, p) => n + p.on_hand, 0),
  )
  expect(f.event_rows.filter((e) => e.event_type === 'ORDER_EXPIRED')).toHaveLength(1)
  expect(f.event_rows.filter((e) => e.event_type === 'PAYMENT_EXPIRED')).toHaveLength(1)
  await page.getByRole('button', { name: '核对付款结果', exact: true }).click()
  expect((await control(request, '/facts')).events).toBe(f.events)
  await expect(page.getByRole('button', { name: '模拟付款', exact: true })).toHaveCount(0)
  await capture(page, request, 'payment-expired')
})
test('payment: server-expired proposal cannot be approved', async ({ page, request }) => {
  await pendingOrder(page, request)
  const id = await quote(page)
  await control(request, '/expire', { proposal_id: id })
  await page.getByRole('button', { name: '批准并模拟付款', exact: true }).click()
  await expect(page.getByRole('heading', { name: '支付提案已过期', exact: true })).toBeVisible()
  const f = await control(request, '/facts')
  expect(f.confirmation_rows).toHaveLength(1)
  expect(f.payment_rows).toHaveLength(0)
  await expect(page.getByRole('button', { name: '批准并模拟付款', exact: true })).toHaveCount(0)
})
test('payment: stale version requires a new quote and new explicit confirmation', async ({
  page,
  request,
}) => {
  const orderId = await pendingOrder(page, request)
  const old = await quote(page)
  await control(request, '/order-condition', { order_id: orderId, condition: 'stale_version' })
  await page.getByRole('button', { name: '批准并模拟付款', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('订单版本已变化')
  expect((await control(request, '/facts')).confirmation_rows).toHaveLength(1)
  await page.getByRole('button', { name: '重新准备付款提案', exact: true }).click()
  await expect(page.getByRole('heading', { name: '请确认模拟付款', exact: true })).toBeVisible()
  await expect(page.getByTestId('payment-proposal-id')).not.toHaveText(old)
  const next = await page.getByTestId('payment-proposal-id').innerText()
  expect(next).not.toBe(old)
  expect((await control(request, '/facts')).payment_rows).toHaveLength(0)
  await page.getByRole('button', { name: '批准并模拟付款', exact: true }).click()
  await expect(page.getByRole('heading', { name: '模拟支付成功', exact: true })).toBeVisible()
  const f = await control(request, '/facts')
  expect(f.payment_rows).toHaveLength(1)
  expect(f.payment_rows[0].action_id).toBe(next)
  expect(f.confirmation_rows.some((c) => c.proposal_id === old)).toBe(false)
})
test('payment: lost committed response is reconciled with GET, without a new payment', async ({
  page,
  request,
}) => {
  const id = await pendingOrder(page, request)
  await quote(page)
  let writes = 0
  await page.route('**/mock-payments', async (route) => {
    writes++
    await route.fetch()
    await route.abort('failed')
  })
  await page.getByRole('button', { name: '批准并模拟付款', exact: true }).click()
  await expect(page.getByRole('heading', { name: '模拟支付成功', exact: true })).toBeVisible()
  expect(writes).toBe(1)
  checkPaid(await control(request, '/facts'), id)
  await capture(page, request, 'payment-lost-response-recovered')
})
test('payment: committed receipt with failed order GET stays unknown until explicit reconciliation', async ({
  page,
  request,
}) => {
  const id = await pendingOrder(page, request)
  await quote(page)
  let committed = false,
    blocked = true,
    writes = 0
  await page.route('**/api/v1/orders/*', (r) =>
    committed && blocked && r.request().method() === 'GET' ? r.abort('timedout') : r.continue(),
  )
  await page.route('**/mock-payments', async (route) => {
    writes++
    await route.fetch()
    committed = true
    await route.abort('timedout')
  })
  await page.getByRole('button', { name: '批准并模拟付款', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('付款结果尚未确定')
  await expect(page.getByRole('heading', { name: '模拟支付成功', exact: true })).toHaveCount(0)
  checkPaid(await control(request, '/facts'), id)
  await capture(page, request, 'payment-outcome-unknown')
  blocked = false
  await page.getByRole('button', { name: '核对付款结果', exact: true }).click()
  await expect(page.getByRole('heading', { name: '模拟支付成功', exact: true })).toBeVisible()
  expect(writes).toBe(1)
  checkPaid(await control(request, '/facts'), id)
  await capture(page, request, 'payment-outcome-reconciled')
})
test('payment: lost proposal response finds the same request and key before any payment', async ({
  page,
  request,
}) => {
  await pendingOrder(page, request)
  const prepares: { body: string | null; key: string | undefined }[] = []
  await page.route('**/payment-proposals', async (route) => {
    prepares.push({
      body: route.request().postData(),
      key: route.request().headers()['idempotency-key'],
    })
    if (prepares.length === 1) {
      await route.fetch()
      await route.abort('timedout')
    } else await route.continue()
  })
  await page.getByRole('button', { name: '模拟付款', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('付款结果尚未确定')
  await page.getByRole('button', { name: '找回原支付提案', exact: true }).click()
  await expect(page.getByRole('heading', { name: '请确认模拟付款', exact: true })).toBeVisible()
  expect(prepares).toHaveLength(2)
  expect(prepares[1]).toEqual(prepares[0])
  const f = await control(request, '/facts')
  expect(f.proposal_rows.filter((p) => p.action_type === 'MOCK_PAYMENT')).toHaveLength(1)
  expect(f.payment_rows).toHaveLength(0)
  expect(f.confirmation_rows).toHaveLength(1)
})
test('payment: lost confirmation is read before an explicit original-operation continuation', async ({
  page,
  request,
}) => {
  const id = await pendingOrder(page, request)
  const proposalId = await quote(page)
  let confirms = 0
  await page.route(`**/proposals/${proposalId}/confirmations`, async (route) => {
    confirms++
    await route.fetch()
    await route.abort('timedout')
  })
  await page.getByRole('button', { name: '批准并模拟付款', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('付款结果尚未确定')
  expect((await control(request, '/facts')).payment_rows).toHaveLength(0)
  await page.getByRole('button', { name: '核对付款结果', exact: true }).click()
  await page.getByRole('button', { name: '继续已批准的模拟付款', exact: true }).click()
  await expect(page.getByRole('heading', { name: '模拟支付成功', exact: true })).toBeVisible()
  expect(confirms).toBe(1)
  checkPaid(await control(request, '/facts'), id)
})
test('payment: refresh and re-login restore the payment quote without automatic approval', async ({
  page,
  request,
}) => {
  const id = await pendingOrder(page, request)
  const pid = await quote(page)
  await page.reload()
  await expect(page.getByText('登录后继续')).toBeVisible()
  await login(page, 'buyer1', true)
  await expect(page.getByTestId('payment-proposal-id')).toHaveText(pid)
  const before = await control(request, '/facts')
  expect(before.confirmation_rows).toHaveLength(1)
  expect(before.payment_rows).toHaveLength(0)
  const storage = await page.evaluate(() => JSON.stringify({ ...sessionStorage }))
  expect(storage).not.toMatch(/eyJ|Bearer|access_token|AgentMall-demo/)
  await page.getByRole('button', { name: '批准并模拟付款', exact: true }).click()
  await expect(page.getByRole('heading', { name: '模拟支付成功', exact: true })).toBeVisible()
  checkPaid(await control(request, '/facts'), id)
})
test('payment: cancelled orders and other buyers have no payment entry or side effects', async ({
  page,
  request,
}) => {
  const id = await pendingOrder(page, request)
  const headers = await auth(request)
  const order = (await control(request, '/facts')).order_rows[0]
  const p = await post(
    request,
    `/orders/${id}/cancel-proposals`,
    { request_id: crypto.randomUUID(), expected_version: order.version },
    headers,
  )
  const c = await post(
    request,
    `/proposals/${p.proposal_id}/confirmations`,
    { decision: 'approve' },
    headers,
  )
  await post(
    request,
    `/orders/${id}/cancel`,
    { proposal_id: p.proposal_id, confirmation_id: c.confirmation_id },
    headers,
  )
  await page.getByRole('button', { name: '刷新订单状态', exact: true }).click()
  await expect(page.getByText('已取消', { exact: true }).first()).toBeVisible()
  await expect(page.getByRole('button', { name: '模拟付款', exact: true })).toHaveCount(0)
  const before = await control(request, '/facts')
  expect(before.payment_rows).toHaveLength(0)
  await page.getByRole('button', { name: '退出登录', exact: true }).click()
  await login(page, 'buyer2', true)
  await expect(page.getByRole('alert')).toContainText('没有访问权限')
  const other = await auth(request, 'buyer2')
  const denied = await request.post(`${API}/orders/${id}/payment-proposals`, {
    headers: { ...other, 'Idempotency-Key': crypto.randomUUID() },
    data: { request_id: crypto.randomUUID(), expected_version: order.version },
  })
  expect(denied.status()).toBe(404)
  const after = await control(request, '/facts')
  expect(after.payment_rows).toHaveLength(0)
  expect(after.proposal_rows).toEqual(before.proposal_rows)
  expect(after.receipts).toBe(before.receipts)
})
test('payment: durable multi-agent checkout reaches the same human payment page', async ({
  page,
  request,
}) => {
  await login(page)
  await page.locator('a[href="/agent/workspace"]').first().click()
  await page.getByLabel('运行模式').selectOption('multi')
  await page.getByRole('button', { name: '创建 Thread', exact: true }).click()
  await page.getByLabel('本次任务').fill('找一款300元以内静音键盘准备购买，送演示宿舍')
  await page.getByRole('button', { name: '启动新 Run', exact: true }).click()
  await page.getByRole('button', { name: '批准并继续工作流', exact: true }).click()
  await expect(page.getByTestId('run-status')).toContainText('COMPLETED')
  await page.locator('a[href^="/orders/"]').first().click()
  const id = page.url().split('/orders/')[1]
  await quote(page)
  const before = await control(request, '/facts')
  expect(before.payment_rows).toHaveLength(0)
  await page.getByRole('button', { name: '批准并模拟付款', exact: true }).click()
  await expect(page.getByRole('heading', { name: '模拟支付成功', exact: true })).toBeVisible()
  checkPaid(await control(request, '/facts'), id)
  await capture(page, request, 'agent-order-payment-succeeded')
})
test('payment: mobile confirmation and paid receipt fit the viewport', async ({
  page,
  request,
}) => {
  await page.setViewportSize({ width: 390, height: 844 })
  const id = await pendingOrder(page, request)
  await quote(page)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await capture(page, request, 'payment-mobile-confirmation')
  await page.getByRole('button', { name: '批准并模拟付款', exact: true }).click()
  await expect(page.getByRole('heading', { name: '模拟支付成功', exact: true })).toBeVisible()
  checkPaid(await control(request, '/facts'), id)
  await capture(page, request, 'payment-mobile-succeeded')
})
test('payment: actual API-client timeout after commit recovers without another execution', async ({
  page,
  request,
}) => {
  test.setTimeout(45000)
  const id = await pendingOrder(page, request)
  await quote(page)
  let writes = 0
  await page.route('**/mock-payments', async (route) => {
    writes++
    await route.fetch()
    // Deliberately exceed ApiClient's real 15s timeout, after the real transaction commits.
    await new Promise((resolve) => setTimeout(resolve, 16000))
    await route.abort('timedout').catch(() => {})
  })
  await page.getByRole('button', { name: '批准并模拟付款', exact: true }).click()
  await expect(page.getByRole('heading', { name: '模拟支付成功', exact: true })).toBeVisible({
    timeout: 22000,
  })
  expect(writes).toBe(1)
  checkPaid(await control(request, '/facts'), id)
})

test('payment: lost reject before commit retries only the original rejection', async ({
  page,
  request,
}) => {
  await pendingOrder(page, request)
  const pid = await quote(page)
  const decisions: string[] = []
  let payments = 0
  page.on('request', (r) => {
    if (r.method() === 'POST' && r.url().endsWith('/mock-payments')) payments++
  })
  await page.route(`**/proposals/${pid}/confirmations`, async (route) => {
    decisions.push(route.request().postData()!)
    if (decisions.length === 1) await route.abort('timedout')
    else await route.continue()
  })
  await page.getByRole('button', { name: '拒绝本次付款', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('付款结果尚未确定')
  await page.getByRole('button', { name: '核对付款结果', exact: true }).click()
  await expect(page.getByRole('button', { name: '批准并模拟付款', exact: true })).toHaveCount(0)
  await page.getByRole('button', { name: '继续拒绝本次付款', exact: true }).click()
  await expect(page.getByRole('heading', { name: '支付提案已拒绝', exact: true })).toBeVisible()
  const f = await control(request, '/facts')
  expect(decisions).toHaveLength(2)
  expect(decisions[1]).toBe(decisions[0])
  expect(payments).toBe(0)
  expect(f.payment_rows).toHaveLength(0)
  expect(f.proposal_rows.filter((p) => p.action_type === 'MOCK_PAYMENT')).toHaveLength(1)
  expect(f.proposal_rows.find((p) => p.id === pid)?.status).toBe('REJECTED')
  expect(f.confirmation_rows.filter((c) => c.proposal_id === pid)).toHaveLength(1)
  await capture(page, request, 'payment-reject-recovered')
})
test('payment: storage unavailable does not block read-only committed-result recovery', async ({
  page,
  request,
}) => {
  const id = await pendingOrder(page, request)
  await quote(page)
  await page.evaluate(() => {
    const original = Storage.prototype.setItem
    Storage.prototype.setItem = function (key: string, value: string) {
      if (key.startsWith('agentmall:mock-payment:'))
        throw new DOMException('Synthetic quota failure', 'QuotaExceededError')
      return original.call(this, key, value)
    }
  })
  let committed = false,
    blocked = true,
    payments = 0
  await page.route('**/api/v1/orders/*', (r) =>
    committed && blocked && r.request().method() === 'GET' ? r.abort('timedout') : r.continue(),
  )
  await page.route('**/mock-payments', async (route) => {
    payments++
    await route.fetch()
    committed = true
    await route.abort('timedout')
  })
  await page.getByRole('button', { name: '批准并模拟付款', exact: true }).click()
  await expect(page.getByText('浏览器无法保存付款引用', { exact: false })).toBeVisible()
  await expect(page.getByRole('heading', { name: '付款结果待核对', exact: true })).toBeVisible()
  checkPaid(await control(request, '/facts'), id)
  blocked = false
  await expect(page.getByRole('button', { name: '核对付款结果', exact: true })).toBeEnabled()
  await page.getByRole('button', { name: '核对付款结果', exact: true }).click()
  await expect(page.getByRole('heading', { name: '模拟支付成功', exact: true })).toBeVisible()
  expect(payments).toBe(1)
  checkPaid(await control(request, '/facts'), id)
  await capture(page, request, 'payment-storage-failure-recovered')
})
