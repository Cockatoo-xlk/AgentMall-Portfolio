import { test, expect } from '@playwright/test'
import type { Page, APIRequestContext } from '@playwright/test'
import { mkdir, writeFile } from 'node:fs/promises'
import path from 'node:path'
const CONTROL = 'http://127.0.0.1:8001/__test'
const key = { 'X-E2E-Key': 'agentmall-local-e2e' }
const PASSWORD = 'AgentMall-demo-2026!' // Synthetic fixture secret only; never part of the web bundle.
const evidenceDir = path.resolve(process.env.AGENTMALL_EVIDENCE_DIR ?? 'evidence/t04')
async function control(request: APIRequestContext, endpoint: string, data?: object) {
  const response =
    data === undefined
      ? await request.get(CONTROL + endpoint, { headers: key })
      : await request.post(CONTROL + endpoint, { headers: key, data })
  expect(response.ok()).toBeTruthy()
  return response.json()
}
async function login(page: Page, user = 'buyer1') {
  await page.goto('/login')
  await page.getByLabel('账号', { exact: true }).fill(user)
  await page.getByLabel('密码', { exact: true }).fill(PASSWORD)
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await expect(page.getByRole('button', { name: '退出登录' })).toBeVisible()
}
async function prepare(page: Page) {
  await page.locator('a[href="/"]').first().click()
  await page
    .getByTestId('product-card')
    .first()
    .getByRole('button', { name: '加入购物车', exact: true })
    .click()
  await page
    .getByRole('link', { name: /购物车/ })
    .first()
    .click()
  await expect(page.getByRole('button', { name: '生成购买提案' })).toBeEnabled()
  await page.getByRole('button', { name: '生成购买提案' }).click()
  await expect(page).toHaveURL(/\/proposals\//)
  await expect(page.getByRole('button', { name: '确认并创建订单' })).toBeVisible()
  return page.url().split('/proposals/')[1]
}
test.beforeEach(async ({ page, request }) => {
  await control(request, '/reset', {})
  await page.route('**/*', (route) =>
    new URL(route.request().url()).hostname === '127.0.0.1' ? route.continue() : route.abort(),
  )
})
test.afterEach(async ({ request }) => {
  const f = await control(request, '/facts')
  expect(f.provider_http_requests).toBe(0)
  expect(f.real_model_calls).toBe(0)
  expect(f.blocked_external_attempts).toBe(0)
})
test('purchase: login failure, buyer role, memory-only token and merchant boundary', async ({
  page,
}) => {
  await page.goto('/login')
  await page.getByLabel('账号', { exact: true }).fill('buyer1')
  await page.getByLabel('密码', { exact: true }).fill('wrong')
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('账号或密码')
  await login(page)
  const storage = await page.evaluate(() => ({
    local: { ...localStorage },
    session: { ...sessionStorage },
  }))
  expect(JSON.stringify(storage)).not.toMatch(/eyJ|access_token|Bearer/)
  await page.reload()
  await expect(page.getByRole('link', { name: '登录', exact: true }).first()).toBeVisible()
  await login(page, 'merchant')
  await page.evaluate(() => {
    history.pushState({}, '', '/cart')
    dispatchEvent(new PopStateEvent('popstate'))
  })
  await expect(page.getByText('当前为商家账号')).toBeVisible()
  await expect(page.getByRole('button', { name: '生成购买提案' })).toHaveCount(0)
})
test('purchase: backend filters, pagination and details', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByTestId('product-card')).toHaveCount(8)
  await page.getByRole('button', { name: '加载更多' }).click()
  await expect(page.getByTestId('product-card')).toHaveCount(12)
  await page.getByLabel('搜索商品').fill('静音')
  await page.getByLabel('最高预算（元）').fill('300')
  await page.getByRole('button', { name: '筛选商品' }).click()
  await expect(page.getByTestId('product-card')).toHaveCount(2)
  await page.getByRole('link', { name: '宿舍静音 K68', exact: true }).click()
  await expect(page.getByRole('heading', { name: '宿舍静音 K68' })).toBeVisible()
  await expect(page.getByText('¥199.00').first()).toBeVisible()
  await expect(page.getByText('静音轴').first()).toBeVisible()
})
test('purchase: cart add edit delete and stale-version reconciliation', async ({
  page,
  request,
}) => {
  await login(page)
  await page.locator('a[href="/"]').first().click()
  await page
    .getByTestId('product-card')
    .first()
    .getByRole('button', { name: '加入购物车', exact: true })
    .click()
  await page
    .getByRole('link', { name: /购物车/ })
    .first()
    .click()
  const input = page.getByRole('spinbutton').first()
  await expect(input).toHaveValue('1')
  await input.fill('2')
  await page.getByRole('button', { name: /更新 .* 数量/ }).click()
  await expect(input).toHaveValue('2')
  const auth = await request.post('http://127.0.0.1:8001/api/v1/auth/login', {
    data: { login: 'buyer1', password: PASSWORD },
  })
  const headers = { Authorization: `Bearer ${(await auth.json()).access_token}` }
  const cart = await (await request.get('http://127.0.0.1:8001/api/v1/cart', { headers })).json()
  await request.put(`http://127.0.0.1:8001/api/v1/cart/items/${cart.items[0].product_id}`, {
    headers,
    data: { quantity: 3, expected_version: cart.version },
  })
  const stale = page.waitForResponse((r) => r.url().includes('/cart/items/') && r.status() === 409)
  await input.fill('4')
  await page.getByRole('button', { name: /更新 .* 数量/ }).click()
  await stale
  await expect(page.getByText(/购物车版本已变化/)).toBeVisible()
  await expect(input).toHaveValue('3')
  const after = await (await request.get('http://127.0.0.1:8001/api/v1/cart', { headers })).json()
  expect(after.items[0].quantity).toBe(3)
  await page.getByRole('button', { name: /移除 / }).click()
  await expect(page.getByText('购物车还是空的')).toBeVisible()
})
test('purchase: rejecting a real proposal creates no order', async ({ page, request }) => {
  await login(page)
  await prepare(page)
  await page.getByRole('button', { name: '拒绝此提案' }).click()
  await expect(page.getByText('提案已拒绝', { exact: true })).toBeVisible()
  const f = await control(request, '/facts')
  expect(f.orders).toBe(0)
  expect(f.reserved).toBe(0)
  expect(f.confirmations).toBe(1)
})
test('purchase: approve, duplicate click, receipt and SQL agree', async ({ page, request }) => {
  await login(page)
  await prepare(page)
  const button = page.getByRole('button', { name: '确认并创建订单' })
  await button.dblclick()
  await expect(page).toHaveURL(/\/orders\//)
  await expect(page.getByRole('heading', { name: '订单已创建' })).toBeVisible()
  const f = await control(request, '/facts')
  expect(f.orders).toBe(1)
  expect(f.reserved).toBe(1)
  expect(f.receipts).toBe(1)
  expect(f.events).toBe(1)
  expect(page.url()).toContain(f.order_rows[0].id)
  await page.getByRole('link', { name: '查看原提案' }).click()
  await expect(page.getByRole('link', { name: '查看订单' })).toBeVisible()
  await expect(page.getByRole('button', { name: '确认并创建订单' })).toHaveCount(0)
  await mkdir(evidenceDir, { recursive: true })
  await writeFile(path.join(evidenceDir, 'manual-purchase.json'), JSON.stringify(f, null, 2))
})
test('purchase: lost committed order response recovers without another order', async ({
  page,
  request,
}) => {
  await login(page)
  await prepare(page)
  let writes = 0
  await page.route('**/api/v1/orders', async (route) => {
    if (route.request().method() === 'POST') {
      writes++
      await route.fetch()
      await route.abort('failed')
    } else await route.continue()
  })
  await page.getByRole('button', { name: '确认并创建订单' }).click()
  await expect(page).toHaveURL(/\/orders\//)
  expect(writes).toBe(1)
  const f = await control(request, '/facts')
  expect(f.orders).toBe(1)
  expect(f.reserved).toBe(1)
})
test('purchase: lost confirmation leaves a recoverable approved proposal', async ({
  page,
  request,
}) => {
  await login(page)
  await prepare(page)
  await page.route(
    '**/confirmations',
    async (route) => {
      await route.fetch()
      await route.abort('failed')
    },
    { times: 1 },
  )
  await page.getByRole('button', { name: '确认并创建订单' }).click()
  await expect(page.getByText(/结果尚未确定/)).toBeVisible()
  expect((await control(request, '/facts')).orders).toBe(0)
  await page.getByRole('button', { name: '继续创建订单' }).click()
  await expect(page).toHaveURL(/\/orders\//)
  expect((await control(request, '/facts')).orders).toBe(1)
})
test('purchase: expired proposal cannot be approved', async ({ page, request }) => {
  await login(page)
  const id = await prepare(page)
  await control(request, '/expire', { proposal_id: id })
  await page.getByRole('button', { name: '刷新提案状态' }).click()
  await expect(page.getByText('提案已过期', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '确认并创建订单' })).toHaveCount(0)
  expect((await control(request, '/facts')).orders).toBe(0)
})
test('purchase: refresh login recovers known proposal; other buyer gets 404', async ({ page }) => {
  await login(page)
  const id = await prepare(page)
  await page.reload()
  await expect(page.getByText('登录后继续')).toBeVisible()
  await page.getByRole('link', { name: '去登录' }).click()
  await page.getByLabel('账号', { exact: true }).fill('buyer1')
  await page.getByLabel('密码', { exact: true }).fill(PASSWORD)
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await expect(page).toHaveURL(new RegExp(`/proposals/${id}`))
  await expect(page.getByRole('button', { name: '确认并创建订单' })).toBeVisible()
  await page.getByRole('button', { name: '退出登录' }).click()
  await page.goto(`/proposals/${id}`)
  await page.getByRole('link', { name: '去登录' }).click()
  await page.getByLabel('账号', { exact: true }).fill('buyer2')
  await page.getByLabel('密码', { exact: true }).fill(PASSWORD)
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('没有访问权限')
})
for (const mode of ['proposal', 'needs_input', 'blocked', 'error'] as const) {
  test(`purchase: agent ${mode} is represented accurately`, async ({ page, request }) => {
    await control(request, '/agent-mode', { mode })
    await login(page)
    await page.locator('a[href="/assistant"]').first().click()
    await page.getByLabel('购物需求').fill('帮我找300元以内静音键盘，购买一件，送到演示宿舍地址。')
    await page.getByRole('button', { name: '发送需求' }).click()
    const status = {
      proposal: '等待确认',
      needs_input: '需要补充信息',
      blocked: 'AI 助手当前未启用',
      error: '暂时未能完成',
    }[mode]
    await expect(page.getByText(status, { exact: mode !== 'blocked' }).first()).toBeVisible()
    const f = await control(request, '/facts')
    expect(f.orders).toBe(0)
    if (mode === 'proposal') {
      await page.getByRole('link', { name: '查看并确认提案' }).click()
      await page.getByRole('button', { name: '确认并创建订单' }).click()
      await expect(page).toHaveURL(/\/orders\//)
      const after = await control(request, '/facts')
      expect(after.orders).toBe(1)
      await mkdir(evidenceDir, { recursive: true })
      await writeFile(
        path.join(evidenceDir, 'agent-fixture-purchase.json'),
        JSON.stringify(after, null, 2),
      )
    }
  })
}
test('purchase: agent network retry preserves request id', async ({ page }) => {
  await login(page)
  await page.locator('a[href="/assistant"]').first().click()
  const ids: string[] = []
  await page.route('**/api/v1/agent/messages', async (route) => {
    ids.push(route.request().postDataJSON().request_id)
    if (ids.length === 1) await route.abort('failed')
    else await route.continue()
  })
  await page.getByLabel('购物需求').fill('准备购买静音键盘一件，演示宿舍地址')
  await page.getByRole('button', { name: '发送需求' }).click()
  await expect(page.getByRole('button', { name: '重试同一请求' })).toBeVisible()
  await page.getByRole('button', { name: '重试同一请求' }).click()
  await expect(page.getByText('等待确认', { exact: true }).first()).toBeVisible()
  expect(ids).toHaveLength(2)
  expect(ids[0]).toBe(ids[1])
})
test('purchase: 401 expires in-memory auth; 404 and network GET show recovery', async ({
  page,
  request,
}) => {
  await login(page)
  await control(request, '/disable-user', { login: 'buyer1' })
  await page.locator('a[href="/orders"]').first().click()
  await expect(page.getByText(/登录已过期/)).toBeVisible()
  await expect(page.getByRole('button', { name: '退出登录' })).toHaveCount(0)
  await page.goto('/products/00000000-0000-0000-0000-000000000099')
  await expect(page.getByRole('alert')).toContainText('不存在')
  await page.route('**/api/v1/products?*', (route) => route.abort('failed'))
  await page.goto('/')
  await expect(page.getByRole('alert').first()).toBeVisible()
  await page.unroute('**/api/v1/products?*')
  await page.getByRole('button', { name: /重试/ }).first().click()
  await expect(page.getByTestId('product-card').first()).toBeVisible()
})
test('purchase: desktop and mobile have no horizontal overflow', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.goto('/')
  await expect(page.getByTestId('product-card').first()).toBeVisible()
  await mkdir(evidenceDir, { recursive: true })
  await page.screenshot({
    path: path.join(evidenceDir, 'catalog-desktop.png'),
    fullPage: true,
    animations: 'disabled',
  })
  await page.locator('a[href="/login"]').first().click()
  await expect(page.getByRole('heading', { name: '登录 AgentMall' })).toBeVisible()
  await page.screenshot({
    path: path.join(evidenceDir, 'login-desktop.png'),
    fullPage: true,
    animations: 'disabled',
  })
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/')
  await expect(page.getByTestId('product-card').first()).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  )
  await page.screenshot({
    path: path.join(evidenceDir, 'catalog-mobile.png'),
    fullPage: true,
    animations: 'disabled',
  })
  await login(page)
  await page.getByTestId('product-card').first().getByRole('link').first().click()
  await expect(page).toHaveURL(/\/products\//)
  await expect(page.locator('.detail-page')).toBeVisible()
  await expect(page.getByRole('button', { name: '加入购物车', exact: true })).toBeEnabled()
  await page.screenshot({
    path: path.join(evidenceDir, 'product-mobile.png'),
    fullPage: true,
    animations: 'disabled',
  })
  await page.getByRole('button', { name: '加入购物车', exact: true }).click()
  await page.locator('a[href="/cart"]').first().click()
  await expect(page.getByRole('button', { name: '生成购买提案' })).toBeEnabled()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  )
  await page.screenshot({
    path: path.join(evidenceDir, 'cart-mobile.png'),
    fullPage: true,
    animations: 'disabled',
  })
  await page.getByRole('button', { name: '生成购买提案' }).click()
  await expect(page.getByRole('button', { name: '确认并创建订单' })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  )
  await page.screenshot({
    path: path.join(evidenceDir, 'proposal-mobile.png'),
    fullPage: true,
    animations: 'disabled',
  })
  await page.getByRole('button', { name: '确认并创建订单' }).click()
  await expect(page.getByRole('heading', { name: '订单已创建' })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  )
  await page.screenshot({
    path: path.join(evidenceDir, 'order-mobile.png'),
    fullPage: true,
    animations: 'disabled',
  })
  await page.locator('a[href="/assistant"]').first().click()
  await expect(page.getByLabel('购物需求')).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  )
  await page.screenshot({
    path: path.join(evidenceDir, 'assistant-mobile.png'),
    fullPage: true,
    animations: 'disabled',
  })
})

test('purchase: lost proposal response reuses the original request and key', async ({
  page,
  request,
}) => {
  await login(page)
  await page
    .getByTestId('product-card')
    .first()
    .getByRole('button', { name: '加入购物车', exact: true })
    .click()
  await page.locator('a[href="/cart"]').first().click()
  const writes: { body: unknown; key: string | undefined }[] = []
  await page.route('**/api/v1/checkout/proposals', async (route) => {
    writes.push({
      body: route.request().postDataJSON(),
      key: route.request().headers()['idempotency-key'],
    })
    if (writes.length === 1) {
      await route.fetch()
      await route.abort('failed')
    } else await route.continue()
  })
  await page.getByRole('button', { name: '生成购买提案' }).click()
  await expect(page.getByRole('alert')).toContainText('结果尚未确定')
  await page.getByRole('button', { name: '核对并重试原提案' }).click()
  await expect(page).toHaveURL(/\/proposals\//)
  expect(writes).toHaveLength(2)
  expect(writes[0]).toEqual(writes[1])
  const f = await control(request, '/facts')
  expect(f.proposals).toBe(1)
  expect(f.orders).toBe(0)
})

test('purchase: agent done recovers the actual order from an existing request', async ({
  page,
  request,
}) => {
  await login(page)
  await page.locator('a[href="/assistant"]').first().click()
  await page.route(
    '**/api/v1/agent/messages',
    async (route) => {
      await route.fetch()
      await route.abort('failed')
    },
    { times: 1 },
  )
  await page.getByLabel('购物需求').fill('找一款静音键盘，300元以内，一件，演示宿舍地址')
  await page.getByRole('button', { name: '发送需求' }).click()
  await expect(page.getByRole('button', { name: '重试同一请求' })).toBeVisible()
  const f = await control(request, '/facts')
  expect(f.proposals).toBe(1)
  const pid = f.proposal_rows[0].id
  const auth = await request.post('http://127.0.0.1:8001/api/v1/auth/login', {
    data: { login: 'buyer1', password: PASSWORD },
  })
  const headers = { Authorization: `Bearer ${(await auth.json()).access_token}` }
  const confirmation = await request.post(
    `http://127.0.0.1:8001/api/v1/proposals/${pid}/confirmations`,
    { headers, data: { decision: 'approve' } },
  )
  const receipt = await request.post('http://127.0.0.1:8001/api/v1/orders', {
    headers: { ...headers, 'Idempotency-Key': `e2e:done:${pid}` },
    data: { proposal_id: pid, confirmation_id: (await confirmation.json()).confirmation_id },
  })
  expect(receipt.status()).toBe(201)
  await control(request, '/agent-mode', { mode: 'done' })
  await page.getByRole('button', { name: '重试同一请求' }).click()
  await expect(page.getByText('已完成核对', { exact: true })).toBeVisible()
  await expect(page.getByRole('link', { name: /查看订单/ }).first()).toBeVisible()
  const after = await control(request, '/facts')
  expect(after.orders).toBe(1)
  expect(after.fake_model_calls).toBe(f.fake_model_calls)
})

test('purchase: cart must be loaded before adding a product', async ({ page }) => {
  let release!: () => void
  const gate = new Promise<void>((resolve) => {
    release = resolve
  })
  await page.route('**/api/v1/cart', async (route) => {
    await gate
    await route.continue()
  })
  await login(page)
  const add = page
    .getByTestId('product-card')
    .first()
    .getByRole('button', { name: '加入购物车', exact: true })
  try {
    await expect(add).toBeDisabled()
  } finally {
    release()
  }
  await expect(add).toBeEnabled()
  await add.click()
  await page.locator('a[href="/cart"]').first().click()
  await expect(page.getByRole('spinbutton').first()).toHaveValue('1')
})

test('purchase: unknown cart write blocks further writes until GET succeeds', async ({
  page,
  request,
}) => {
  await login(page)
  await page
    .getByTestId('product-card')
    .first()
    .getByRole('button', { name: '加入购物车', exact: true })
    .click()
  await page.locator('a[href="/cart"]').first().click()
  const quantity = page.getByRole('spinbutton').first()
  await expect(quantity).toHaveValue('1')
  await page.route('**/api/v1/cart', (route) => route.abort('failed'), { times: 1 })
  let writes = 0
  await page.route('**/api/v1/cart/items/*', async (route) => {
    writes++
    await route.fetch()
    await route.abort('failed')
  })
  await quantity.fill('2')
  await page.getByRole('button', { name: /更新 .* 数量/ }).click()
  await expect(page.getByRole('alert')).toContainText('购物车状态待核对')
  await expect(page.getByRole('button', { name: '生成购买提案' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: /更新 .* 数量/ })).toHaveCount(0)
  await page.getByRole('button', { name: '核对购物车' }).click()
  await expect(page.getByRole('spinbutton').first()).toHaveValue('2')
  expect(writes).toBe(1)
  expect((await control(request, '/facts')).orders).toBe(0)
})

test('purchase: browser clock cannot override a valid server proposal', async ({
  page,
  request,
}) => {
  await login(page)
  await page.clock.setFixedTime(new Date(Date.now() + 600_000))
  await prepare(page)
  await expect(page.getByText('等待确认', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: '确认并创建订单' }).click()
  await expect(page).toHaveURL(/\/orders\//)
  expect((await control(request, '/facts')).orders).toBe(1)
})

test('purchase: a delisted cart product can be removed after a definitive checkout failure', async ({
  page,
  request,
}) => {
  await login(page)
  await page
    .getByTestId('product-card')
    .first()
    .getByRole('button', { name: '加入购物车', exact: true })
    .click()
  await page.locator('a[href="/cart"]').first().click()
  await expect(page.getByRole('button', { name: '生成购买提案' })).toBeEnabled()
  const f = await control(request, '/facts')
  await control(request, '/delist-product', { product_id: f.product_rows[0].id })
  const failed = page.waitForResponse(
    (response) => response.url().endsWith('/checkout/proposals') && response.status() === 404,
  )
  await page.getByRole('button', { name: '生成购买提案' }).click()
  await failed
  await expect(page.getByRole('button', { name: /移除 / })).toBeEnabled()
  await page.getByRole('button', { name: /移除 / }).click()
  await expect(page.getByText('购物车还是空的')).toBeVisible()
  const after = await control(request, '/facts')
  expect(after.proposals).toBe(0)
  expect(after.orders).toBe(0)
})
