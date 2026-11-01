import { test, expect } from '@playwright/test'
import { API_ORIGIN } from './environment'
import type { APIRequestContext, Page } from '@playwright/test'
import { mkdir, writeFile } from 'node:fs/promises'
import path from 'node:path'
import type { CartDTO } from '../src/api/types'

const API = API_ORIGIN + '/api/v1'
const key = { 'X-E2E-Key': 'agentmall-local-e2e' }
const password = 'AgentMall-demo-2026!'
const evidence = path.resolve(process.env.AGENTMALL_CART_EVIDENCE_DIR ?? 'test-results/cart')
async function control(request: APIRequestContext, endpoint: string, data?: object) {
  const response =
    data === undefined
      ? await request.get(API_ORIGIN + '/__test' + endpoint, { headers: key })
      : await request.post(API_ORIGIN + '/__test' + endpoint, { headers: key, data })
  expect(response.ok(), await response.text()).toBeTruthy()
  return response.json()
}
async function auth(request: APIRequestContext, login = 'buyer1') {
  const response = await request.post(API + '/auth/login', { data: { login, password } })
  expect(response.ok()).toBeTruthy()
  return { Authorization: 'Bearer ' + (await response.json()).access_token }
}
async function login(page: Page, current = false) {
  if (current) await page.getByRole('link', { name: '去登录' }).click()
  else await page.goto('/login')
  await page.getByLabel('账号', { exact: true }).fill('buyer1')
  await page.getByLabel('密码', { exact: true }).fill(password)
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await expect(page.getByRole('button', { name: '退出登录' })).toBeVisible()
}
async function cartProposal(page: Page) {
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
  return page.url().split('/proposals/')[1]
}
async function capture(page: Page, request: APIRequestContext, name: string) {
  await mkdir(evidence, { recursive: true })
  await writeFile(
    path.join(evidence, name + '.json'),
    JSON.stringify(await control(request, '/facts'), null, 2),
  )
  await page.evaluate(() => window.scrollTo(0, 0))
  await page.screenshot({
    path: path.join(evidence, name + '.png'),
    fullPage: true,
    animations: 'disabled',
  })
}
test.beforeEach(async ({ page, request }) => {
  await control(request, '/reset', {})
  await page.route('**/*', (r) =>
    new URL(r.request().url()).hostname === '127.0.0.1' ? r.continue() : r.abort(),
  )
})
test.afterEach(async ({ request }, info) => {
  const facts = await control(request, '/facts')
  expect(facts.provider_http_requests).toBe(0)
  expect(facts.real_model_calls).toBe(0)
  expect(facts.blocked_external_attempts).toBe(0)
  await mkdir(evidence, { recursive: true })
  const name = info.testId.replace(/[^A-Za-z0-9_-]/g, '_')
  await writeFile(
    path.join(evidence, `case-${name}.json`),
    JSON.stringify(
      { title: info.title, status: info.status, expected: info.expectedStatus, facts },
      null,
      2,
    ),
  )
})
test('cart checkout: reservation consumes server cart before payment and survives relogin', async ({
  page,
  request,
}) => {
  await cartProposal(page)
  await page.getByRole('button', { name: '确认并创建订单' }).click()
  await expect(page).toHaveURL(/\/orders\//)
  const headers = await auth(request)
  const cart = await (await request.get(API + '/cart', { headers })).json()
  expect(cart.items).toEqual([])
  expect(cart.version).toBe(2)
  await expect(page.locator('.cart-count')).toHaveText('0')
  const before = await control(request, '/facts')
  expect(before.order_rows[0].status).toBe('PENDING_PAYMENT')
  expect(before.reserved).toBe(1)
  await capture(page, request, 'cart-consumed-before-payment')
  await page.getByRole('button', { name: '模拟付款', exact: true }).click()
  await page.getByRole('button', { name: '批准并模拟付款', exact: true }).click()
  await expect(page.getByRole('heading', { name: '模拟支付成功', exact: true })).toBeVisible()
  await expect(page.locator('.cart-count')).toHaveText('0')
  const after = await control(request, '/facts')
  expect(after.orders).toBe(1)
  expect(after.payment_rows).toHaveLength(1)
  expect(after.order_rows[0].status).toBe('PAID')
  expect(after.reserved).toBe(0)
  const orderPath = new URL(page.url()).pathname
  await page.reload()
  await expect(page.getByRole('link', { name: '去登录' })).toBeVisible()
  await login(page, true)
  await expect(page).toHaveURL(new RegExp(orderPath))
  await expect(page.locator('.cart-count')).toHaveText('0')
  expect(
    (await (await request.get(API + '/cart', { headers: await auth(request) })).json()).version,
  ).toBe(2)
  await page.locator('a[href="/cart"]').first().click()
  await expect(page.getByRole('heading', { name: '购物车还是空的' })).toBeVisible()
  await capture(page, request, 'cart-empty-after-payment-relogin')
})

function cartContents(cart: {
  id: string
  version: number
  items: { product_id: string; quantity: number }[]
}) {
  return {
    id: cart.id,
    version: cart.version,
    items: cart.items.map((item) => ({ product_id: item.product_id, quantity: item.quantity })),
  }
}
function assertInventory(
  cart: CartDTO,
  facts: { product_rows: { id: string; on_hand: number; reserved: number }[] },
) {
  for (const item of cart.items) {
    const product = facts.product_rows.find((p) => p.id === item.product_id)!
    expect(item.available).toBe(product.on_hand - product.reserved)
  }
}
async function getCart(request: APIRequestContext, headers: Record<string, string>) {
  const response = await request.get(API + '/cart', { headers })
  expect(response.ok()).toBeTruthy()
  return response.json()
}
async function post(
  request: APIRequestContext,
  endpoint: string,
  data: object,
  headers: Record<string, string>,
  idempotencyKey = crypto.randomUUID(),
) {
  const response = await request.post(API + endpoint, {
    headers: { ...headers, 'Idempotency-Key': idempotencyKey },
    data,
  })
  expect(response.ok(), await response.text()).toBeTruthy()
  return response.json()
}
async function put(
  request: APIRequestContext,
  headers: Record<string, string>,
  productId: string,
  quantity: number,
  version: number,
) {
  const response = await request.put(API + '/cart/items/' + productId, {
    headers,
    data: { quantity, expected_version: version },
  })
  expect(response.ok(), await response.text()).toBeTruthy()
  return response.json()
}
function checkoutReceipt(facts: Awaited<ReturnType<typeof control>>, proposalId: string) {
  return facts.receipt_rows.find((r: { action_id: string }) => r.action_id === proposalId).result
}
for (const change of ['add_b', 'modify_a', 'remove_readd_a'] as const) {
  test(`cart checkout: ${change} after quote preserves changed cart and old purchase snapshot`, async ({
    page,
    request,
  }) => {
    if (change === 'add_b') await page.setViewportSize({ width: 390, height: 844 })
    const pid = await cartProposal(page)
    const headers = await auth(request)
    const cart = await getCart(request, headers)
    const productA = cart.items[0].product_id
    const products = await (await request.get(API + '/products', { headers })).json()
    const productB = products.items.find((p: { id: string }) => p.id !== productA).id
    let version = cart.version
    if (change === 'remove_readd_a') {
      const removed = await request.delete(API + '/cart/items/' + productA, {
        headers,
        data: { expected_version: version },
      })
      expect(removed.ok()).toBeTruthy()
      version = (await removed.json()).version
    }
    const changed = await put(
      request,
      headers,
      change === 'add_b' ? productB : productA,
      2,
      version,
    )
    await page.getByRole('button', { name: '确认并创建订单' }).click()
    await expect(page).toHaveURL(/\/orders\//)
    await expect(page.getByRole('status').filter({ hasText: '购物车在提案后已变化' })).toBeVisible()
    expect(cartContents(await getCart(request, headers))).toEqual(cartContents(changed))
    await expect(page.locator('.cart-count')).toHaveText(change === 'add_b' ? '3' : '2')
    const facts = await control(request, '/facts')
    expect(facts.orders).toBe(1)
    assertInventory(await getCart(request, headers), facts)
    expect(checkoutReceipt(facts, pid).cart_consumption).toBe('SKIPPED_CART_CHANGED')
    expect(facts.cart_rows.find((c: { id: string }) => c.id === cart.id).version).toBe(
      changed.version,
    )
    const order = await (
      await request.get(API + '/orders/' + facts.order_rows[0].id, { headers })
    ).json()
    expect(order.items).toHaveLength(1)
    expect(order.items[0]).toMatchObject({ product_id: productA, quantity: 1 })
    const proposal = await (await request.get(API + '/proposals/' + pid, { headers })).json()
    expect(proposal.canonical_payload.cart_source.version).toBe(1)
    expect(proposal.canonical_payload.items[0].quantity).toBe(1)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    await capture(page, request, 'cart-preserved-' + change)
  })
}

test('cart checkout: item added after commit before response delivery is retained', async ({
  page,
  request,
}) => {
  const pid = await cartProposal(page)
  const headers = await auth(request)
  const original = await getCart(request, headers)
  const products = await (await request.get(API + '/products', { headers })).json()
  const productB = products.items.find(
    (p: { id: string }) => p.id !== original.items[0].product_id,
  ).id
  let writes = 0
  await page.route('**/api/v1/orders', async (route) => {
    if (route.request().method() !== 'POST') return route.continue()
    writes++
    const committed = await route.fetch()
    expect(committed.status()).toBe(201)
    const cart = await getCart(request, headers)
    expect(cart.items).toEqual([])
    await put(request, headers, productB, 1, cart.version)
    await route.fulfill({ response: committed })
  })
  await page.getByRole('button', { name: '确认并创建订单' }).dblclick()
  await expect(page).toHaveURL(/\/orders\//)
  await expect(page.locator('.cart-count')).toHaveText('1')
  expect(writes).toBe(1)
  const facts = await control(request, '/facts')
  expect(facts.orders).toBe(1)
  expect(checkoutReceipt(facts, pid).cart_consumption).toBe('CONSUMED')
  expect(facts.cart_rows[0].version).toBe(3)
  expect(facts.cart_item_rows).toHaveLength(1)
  expect(facts.cart_item_rows[0]).toMatchObject({ product_id: productB, quantity: 1 })
  await capture(page, request, 'cart-postcommit-new-item')
})

test('cart checkout: independent Agent order for same SKU never consumes existing cart', async ({
  page,
  request,
}) => {
  await cartProposal(page)
  const headers = await auth(request)
  const before = await getCart(request, headers)
  await page.locator('a[href="/agent/workspace"]').first().click()
  await page.getByLabel('运行模式').selectOption('multi')
  await page.getByRole('button', { name: '创建 Thread', exact: true }).click()
  await page.getByLabel('本次任务').fill('找一款300元以内静音键盘准备购买，送演示宿舍')
  await page.getByRole('button', { name: '启动新 Run', exact: true }).click()
  await page.getByRole('button', { name: '批准并继续工作流', exact: true }).click()
  await expect(page.getByTestId('run-status')).toContainText('COMPLETED')
  await page.locator('a[href^="/orders/"]').first().click()
  await expect(page.locator('.cart-count')).toHaveText('1')
  await expect(
    page.getByRole('status').filter({ hasText: '未绑定可消费的购物车快照' }),
  ).toBeVisible()
  expect(cartContents(await getCart(request, headers))).toEqual(cartContents(before))
  const facts = await control(request, '/facts')
  expect(facts.orders).toBe(1)
  assertInventory(await getCart(request, headers), facts)
  expect(facts.checkpoint_rows).toBeGreaterThan(0)
  expect(facts.run_rows[0].status).toBe('COMPLETED')
  const p = facts.proposal_rows.find(
    (p: { id: string }) => p.id === facts.order_rows[0].proposal_id,
  )
  expect(p.canonical_payload.cart_source).toBeUndefined()
  expect(p.canonical_payload.items[0].product_id).toBe(before.items[0].product_id)
  expect(checkoutReceipt(facts, p.id).cart_consumption).toBe('NOT_APPLICABLE')
  await capture(page, request, 'cart-agent-independent-preserved')
})

test('cart checkout: rejected purchase proposal retains server cart', async ({ page, request }) => {
  await cartProposal(page)
  await page.getByRole('button', { name: '拒绝此提案', exact: true }).click()
  await expect(page.getByRole('heading', { name: '提案已拒绝' })).toBeVisible()
  const facts = await control(request, '/facts')
  expect(facts.orders).toBe(0)
  expect(facts.cart_rows[0].version).toBe(1)
  expect(facts.cart_item_rows).toHaveLength(1)
  expect(facts.reserved).toBe(0)
  expect(facts.confirmation_rows[0]).toMatchObject({ decision: 'reject', consumed_at: null })
})

test('cart checkout: expired purchase proposal retains server cart', async ({ page, request }) => {
  const pid = await cartProposal(page)
  await control(request, '/expire', { proposal_id: pid })
  await page.getByRole('button', { name: '刷新提案状态' }).click()
  await expect(page.getByRole('heading', { name: '提案已过期' })).toBeVisible()
  await expect(page.getByRole('button', { name: '确认并创建订单' })).toHaveCount(0)
  const facts = await control(request, '/facts')
  expect(facts.orders).toBe(0)
  expect(facts.cart_rows[0].version).toBe(1)
  expect(facts.cart_item_rows).toHaveLength(1)
  expect(facts.reserved).toBe(0)
})

test('cart checkout: stock exhausted by another buyer cannot consume cart', async ({
  page,
  request,
}) => {
  const pid = await cartProposal(page)
  const headers = await auth(request)
  const cart = await getCart(request, headers)
  const other = await auth(request, 'buyer2')
  for (let n = 0; n < 2; n++) {
    const p = await post(
      request,
      '/checkout/proposals',
      {
        request_id: crypto.randomUUID(),
        address_label: 'demo_dorm',
        items: [{ product_id: cart.items[0].product_id, quantity: 10 }],
      },
      other,
    )
    const c = await post(
      request,
      `/proposals/${p.proposal_id}/confirmations`,
      { decision: 'approve' },
      other,
    )
    await post(
      request,
      '/orders',
      { proposal_id: p.proposal_id, confirmation_id: c.confirmation_id },
      other,
    )
  }
  await page.getByRole('button', { name: '确认并创建订单' }).click()
  await expect(page.getByRole('alert')).toBeVisible()
  expect(cartContents(await getCart(request, headers))).toEqual(cartContents(cart))
  const facts = await control(request, '/facts')
  expect(facts.orders).toBe(2)
  expect(facts.reserved).toBe(20)
  assertInventory(await getCart(request, headers), facts)
  expect(
    facts.confirmation_rows.find((c: { proposal_id: string }) => c.proposal_id === pid).consumed_at,
  ).toBeNull()
  expect(facts.cart_rows.find((c: { id: string }) => c.id === cart.id).version).toBe(1)
})

test('cart checkout: injected precommit failure rolls back cart then explicit retry commits once', async ({
  page,
  request,
}) => {
  const pid = await cartProposal(page)
  await control(request, '/checkout-failure', { enabled: true })
  await page.getByRole('button', { name: '确认并创建订单' }).click()
  await expect(page.getByRole('alert')).toContainText('结果尚未确定')
  const failed = await control(request, '/facts')
  expect(failed.orders).toBe(0)
  expect(failed.events).toBe(0)
  expect(failed.reserved).toBe(0)
  expect(failed.cart_rows[0].version).toBe(1)
  expect(failed.cart_item_rows).toHaveLength(1)
  expect(failed.confirmation_rows[0].consumed_at).toBeNull()
  await capture(page, request, 'cart-rollback-kept')
  await control(request, '/checkout-failure', { enabled: false })
  await page.getByRole('button', { name: '继续创建订单' }).click()
  await expect(page).toHaveURL(/\/orders\//)
  await expect(page.locator('.cart-count')).toHaveText('0')
  const facts = await control(request, '/facts')
  expect(facts.orders).toBe(1)
  expect(facts.cart_rows[0].version).toBe(2)
  expect(facts.cart_item_rows).toEqual([])
  expect(checkoutReceipt(facts, pid).cart_consumption).toBe('CONSUMED')
})

test('cart checkout: lost committed response recovers receipt and cross-user access has no effect', async ({
  page,
  request,
}) => {
  const pid = await cartProposal(page)
  let writes = 0
  await page.route('**/api/v1/orders', async (route) => {
    if (route.request().method() !== 'POST') return route.continue()
    writes++
    expect((await route.fetch()).status()).toBe(201)
    await route.abort('failed')
  })
  await page.getByRole('button', { name: '确认并创建订单' }).click()
  await expect(page).toHaveURL(/\/orders\//)
  await expect(page.locator('.cart-count')).toHaveText('0')
  const facts = await control(request, '/facts')
  expect(writes).toBe(1)
  expect(facts.orders).toBe(1)
  expect(facts.cart_rows[0].version).toBe(2)
  expect(facts.cart_item_rows).toEqual([])
  const headers = await auth(request)
  const proposal = await (await request.get(API + '/proposals/' + pid, { headers })).json()
  const body = { proposal_id: pid, confirmation_id: proposal.confirmation.confirmation_id }
  expect(
    (
      await request.post(API + '/orders', {
        headers: { ...headers, 'Idempotency-Key': `web:order:${pid}` },
        data: body,
      })
    ).status(),
  ).toBe(200)
  const other = await auth(request, 'buyer2')
  const denied = await request.post(API + '/orders', {
    headers: { ...other, 'Idempotency-Key': crypto.randomUUID() },
    data: body,
  })
  expect(denied.status()).toBe(404)
  expect(await denied.text()).not.toContain(facts.order_rows[0].id)
  const after = await control(request, '/facts')
  expect(after.cart_rows).toEqual(facts.cart_rows)
  expect(after.cart_item_rows).toEqual(facts.cart_item_rows)
  expect(after.orders).toBe(1)
  await capture(page, request, 'cart-lost-response-recovered')
})

test('cart checkout: known proposal receipt refreshes stale badge without repeating execution', async ({
  page,
  request,
}) => {
  const pid = await cartProposal(page)
  const headers = await auth(request)
  const c = await post(request, `/proposals/${pid}/confirmations`, { decision: 'approve' }, headers)
  await post(request, '/orders', { proposal_id: pid, confirmation_id: c.confirmation_id }, headers)
  await expect(page.locator('.cart-count')).toHaveText('1')
  await page.getByRole('button', { name: '刷新提案状态' }).click()
  await expect(page.locator('.cart-count')).toHaveText('0')
  await page.getByRole('link', { name: '查看订单', exact: true }).click()
  await expect(page.locator('.cart-count')).toHaveText('0')
  const facts = await control(request, '/facts')
  expect(facts.orders).toBe(1)
  expect(facts.cart_rows[0].version).toBe(2)
  expect(facts.cart_item_rows).toEqual([])
})

test('cart checkout: failed cart refresh keeps order success and unknown quantity until GET recovery', async ({
  page,
  request,
}) => {
  await cartProposal(page)
  await page.route('**/api/v1/cart', (route) => route.abort('failed'), { times: 1 })
  await page.getByRole('button', { name: '确认并创建订单' }).click()
  await expect(page).toHaveURL(/\/orders\//)
  await expect(page.getByRole('alert')).toContainText('订单已创建，但购物车最新状态尚未核对')
  await expect(page.locator('.cart-count')).toHaveText('—')
  const facts = await control(request, '/facts')
  expect(facts.orders).toBe(1)
  expect(facts.order_rows[0].status).toBe('PENDING_PAYMENT')
  expect(facts.cart_rows[0].version).toBe(2)
  expect(facts.cart_item_rows).toEqual([])
  await capture(page, request, 'cart-read-unknown')
  await page.locator('a[href="/cart"]').first().click()
  await page.getByRole('button', { name: '核对购物车', exact: true }).click()
  await expect(page.getByRole('heading', { name: '购物车还是空的' })).toBeVisible()
  await expect(page.locator('.cart-count')).toHaveText('0')
  expect((await control(request, '/facts')).orders).toBe(1)
})

test('cart checkout: failed latest GET preserves unknown state when older empty response arrives', async ({
  page,
  request,
}) => {
  await cartProposal(page)
  const headers = await auth(request)
  const original = await getCart(request, headers)
  const products = await (await request.get(API + '/products', { headers })).json()
  const productB = products.items.find((p: { id: string }) => p.id !== original.items[0].product_id)
  let release!: () => void
  let observed!: () => void
  const held = new Promise<void>((r) => {
    observed = r
  })
  const gate = new Promise<void>((r) => {
    release = r
  })
  await page.route(
    '**/api/v1/cart',
    async (route) => {
      const response = await route.fetch()
      expect((await response.json()).version).toBe(2)
      observed()
      await gate
      await route.fulfill({ response })
    },
    { times: 1 },
  )
  try {
    await page.getByRole('button', { name: '确认并创建订单' }).click()
    await held
    await put(request, headers, productB.id, 1, 2)
    await page.locator('a[href="/"]').first().click()
    await page
      .getByTestId('product-card')
      .filter({ hasText: productB.name })
      .getByRole('button', { name: '加入购物车', exact: true })
      .click()
    await expect(page.getByRole('status').filter({ hasText: '购物车版本已变化' })).toBeVisible()
    const orderId = (await control(request, '/facts')).order_rows[0].id
    await page.route('**/api/v1/cart', (route) => route.abort('failed'), { times: 1 })
    await page.locator('a[href="/orders"]').first().click()
    await page.locator(`a[href="/orders/${orderId}"]`).click()
    await expect(page.getByRole('alert')).toContainText('购物车最新状态尚未核对')
    await expect(page.locator('.cart-count')).toHaveText('—')
    const oldResponse = page.waitForResponse(
      (r) => r.url().endsWith('/api/v1/cart') && r.status() === 200,
    )
    release()
    await (await oldResponse).finished()
    // Two rendering frames settle the fulfilled body and queued React update, without random sleeps.
    await page.evaluate(
      () =>
        new Promise<void>((resolve) =>
          requestAnimationFrame(() => requestAnimationFrame(() => resolve())),
        ),
    )
    await expect(page.locator('.cart-count')).toHaveText('—')
    await expect(page.getByRole('alert')).toContainText('购物车最新状态尚未核对')
    await page.locator('a[href="/cart"]').first().click()
    await page.getByRole('button', { name: '核对购物车', exact: true }).click()
    await expect(page.getByRole('link', { name: productB.name, exact: true })).toBeVisible()
    const facts = await control(request, '/facts')
    expect(facts.orders).toBe(1)
    expect(facts.cart_rows[0].version).toBe(3)
    expect(facts.cart_item_rows).toHaveLength(1)
    expect(facts.cart_item_rows[0]).toMatchObject({ product_id: productB.id, quantity: 1 })
  } finally {
    release()
  }
})
