import { test, expect } from '@playwright/test'
import type { APIRequestContext, Page } from '@playwright/test'
import { API_ORIGIN } from './environment'
import type {
  Confirmation,
  Order,
  Page as ResultPage,
  Product,
  Proposal,
  Receipt,
} from '../src/api/types'

const api = API_ORIGIN + '/api/v1'
const password = 'AgentMall-demo-2026!'

test.beforeEach(async ({ page, request }) => {
  await page.route('**/*', (route) =>
    new URL(route.request().url()).hostname === '127.0.0.1' ? route.continue() : route.abort(),
  )
  const headers = { 'X-E2E-Key': 'agentmall-local-e2e' }
  const health = await request.get(API_ORIGIN + '/__test/health', { headers })
  if (health.status() === 404) return // Plain API on the separately owned merchant smoke DB.
  expect(health.ok()).toBeTruthy()
  const status = await health.json()
  expect(status.fixture_mode).toBe('fake-model-real-fastapi-postgresql')
  expect(status.schema).toMatch(/^test_[0-9a-f]{32}$/)
  const reset = await request.post(API_ORIGIN + '/__test/reset', { headers, data: {} })
  expect(reset.ok()).toBeTruthy()
})

async function login(page: Page, user: string) {
  await page.goto('/login')
  await page.getByLabel('账号', { exact: true }).fill(user)
  await page.getByLabel('密码', { exact: true }).fill(password)
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await expect(page.getByRole('button', { name: '退出登录' })).toBeVisible()
}

async function auth(request: APIRequestContext, login: string) {
  const result = await request.post(api + '/auth/login', {
    data: { login, password },
  })
  expect(result.ok()).toBeTruthy()
  return { Authorization: `Bearer ${(await result.json()).access_token}` }
}

async function post<T>(
  request: APIRequestContext,
  headers: Record<string, string>,
  path: string,
  data: object,
): Promise<T> {
  const response = await request.post(api + path, {
    headers: { ...headers, 'Idempotency-Key': crypto.randomUUID() },
    data,
  })
  if (!response.ok()) {
    const body = await response.json().catch(() => null)
    const code = typeof body?.code === 'string' && /^[A-Z_]+$/.test(body.code) ? body.code : ''
    throw new Error(`Fixture ${path}: HTTP ${response.status()} ${code}`)
  }
  return response.json()
}

async function orderFixture(request: APIRequestContext, headers: Record<string, string>) {
  const products: ResultPage<Product> = await (
    await request.get(api + '/products', { headers })
  ).json()
  const proposal = await post<Proposal>(request, headers, '/checkout/proposals', {
    request_id: crypto.randomUUID(),
    address_label: 'demo_dorm',
    items: [{ product_id: products.items[0].id, quantity: 1 }],
  })
  async function confirmation(proposal: Proposal) {
    return post<Confirmation>(
      request,
      headers,
      `/proposals/${proposal.proposal_id}/confirmations`,
      {
        decision: 'approve',
      },
    )
  }
  const checkout = await post<Receipt>(request, headers, '/orders', {
    proposal_id: proposal.proposal_id,
    confirmation_id: (await confirmation(proposal)).confirmation_id,
  })
  const orderPath = `/orders/${checkout.order_id}`
  const order = async (): Promise<Order> => (await request.get(api + orderPath, { headers })).json()
  const payment = await post<Proposal>(request, headers, orderPath + '/payment-proposals', {
    request_id: crypto.randomUUID(),
    expected_version: (await order()).version,
  })
  await post(request, headers, orderPath + '/mock-payments', {
    proposal_id: payment.proposal_id,
    confirmation_id: (await confirmation(payment)).confirmation_id,
  })
  return { order, confirmation }
}

async function findRecord(page: Page, listName: string, label: string) {
  const list = page.getByRole('region', { name: listName })
  const row = list.getByRole('button', { name: label, exact: true })
  const next = list.getByRole('button', { name: '下一页' })
  for (let number = 1; ; number++) {
    await expect(list.getByText(`第 ${number} 页`, { exact: true })).toBeVisible()
    await expect(list.getByText('正在读取服务端状态…')).toHaveCount(0)
    if (await row.isVisible()) return row
    if (!(await next.isEnabled())) {
      await expect(row).toBeVisible()
      return row
    }
    await next.click()
  }
}

async function openOrder(page: Page, id: string) {
  await page.getByRole('link', { name: '商家工作台' }).click()
  await (await findRecord(page, '订单列表', `查看订单 ${id}`)).click()
  return page.getByRole('region', { name: '订单详情' })
}

test('merchant ships, delivers, approves a return and explicitly executes one mock refund', async ({
  page,
  request,
}, testInfo) => {
  const buyer = await auth(request, 'buyer1')
  const { order, confirmation } = await orderFixture(request, buyer)
  const id = (await order()).id
  const writes: string[] = []
  const consoleMessages: string[] = []
  page.on('request', (r) => {
    const pathname = new URL(r.url()).pathname
    if (r.method() === 'POST' && !pathname.endsWith('/auth/login')) writes.push(pathname)
  })
  page.on('console', (message) => consoleMessages.push(message.text()))

  await page.setViewportSize({ width: 1280, height: 1600 })
  await login(page, 'merchant')
  const detail = await openOrder(page, id)
  await expect(detail.getByText('已支付', { exact: true })).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('paid-order.png'), animations: 'disabled' })
  await expect(detail.getByRole('button', { name: '确认送达' })).toHaveCount(0)
  await detail.getByRole('button', { name: '发货', exact: true }).click()
  await detail.getByRole('button', { name: '确认送达' }).click()
  await expect(detail.getByText('已签收', { exact: true })).toBeVisible()
  const delivered = await order()
  const proposal = await post<Proposal>(request, buyer, '/after-sales/proposals', {
    request_id: crypto.randomUUID(),
    expected_version: delivered.version,
    order_id: id,
    reason_code: 'QUALITY_ISSUE',
    description: '合成售后验收',
  })
  const returned = await post<{ case_id: string }>(request, buyer, '/after-sales', {
    proposal_id: proposal.proposal_id,
    confirmation_id: (await confirmation(proposal)).confirmation_id,
  })
  await page.getByRole('button', { name: '售后管理' }).click()
  await page.getByLabel('售后状态').selectOption('REQUESTED')
  const caseLabel = `查看售后 ${returned.case_id}`
  await (await findRecord(page, '售后列表', caseLabel)).click()
  const afterSales = page.getByRole('region', { name: '售后详情' })
  await expect(afterSales.getByRole('button', { name: '确认收到退货' })).toHaveCount(0)
  await afterSales.getByLabel('审核说明').fill('验收通过')
  await afterSales.getByRole('button', { name: '审核通过' }).click()
  await afterSales.getByRole('button', { name: '确认收到退货' }).click()
  await page.getByLabel('售后状态').selectOption('RECEIVED')
  await findRecord(page, '售后列表', caseLabel)
  await afterSales.getByRole('button', { name: '生成模拟退款提案' }).click()
  await expect(afterSales.getByText('退款快照', { exact: true })).toBeVisible()
  await expect(afterSales.getByRole('button', { name: '执行模拟退款' })).toHaveCount(0)
  await page.screenshot({
    path: testInfo.outputPath('refund-proposal.png'),
    fullPage: true,
    animations: 'disabled',
  })
  let markCommitted!: () => void
  let releaseResponse!: () => void
  const committed = new Promise<void>((resolve) => {
    markCommitted = resolve
  })
  const release = new Promise<void>((resolve) => {
    releaseResponse = resolve
  })
  await page.route(
    '**/api/v1/proposals/*/confirmations',
    async (route) => {
      const response = await route.fetch()
      expect(response.status()).toBe(201)
      markCommitted()
      await release
      await route.fulfill({ response })
    },
    { times: 1 },
  )
  await afterSales.getByRole('button', { name: '批准退款提案' }).click()
  try {
    await committed
    await afterSales.getByRole('button', { name: '查看关联订单' }).click()
    await expect(detail.getByText('已签收', { exact: true })).toBeVisible()
    await page.getByRole('button', { name: '售后管理' }).click()
    await expect(afterSales.getByText('已收到退货', { exact: true })).toBeVisible()
    await expect(afterSales.getByRole('button', { name: '批准退款提案' })).toBeDisabled()
  } finally {
    releaseResponse()
  }
  await expect(afterSales.getByRole('button', { name: '执行模拟退款' })).toBeEnabled()
  await afterSales.getByRole('button', { name: '刷新售后详情' }).click()
  await expect(afterSales.getByRole('button', { name: '执行模拟退款' })).toBeEnabled()
  expect(writes.filter((path) => path.endsWith('/refund'))).toHaveLength(0)

  expect((await order()).status).toBe('DELIVERED')
  await page.route(
    `**/api/v1/merchant/after-sales/${returned.case_id}/refund`,
    async (route) => {
      const committed = await route.fetch()
      expect(committed.status()).toBe(201)
      await route.abort('failed')
    },
    { times: 1 },
  )
  await afterSales.getByRole('button', { name: '执行模拟退款' }).click()
  await expect(afterSales.getByRole('alert')).toContainText('结果尚未确定')
  await afterSales.getByRole('button', { name: '核对退款提案状态' }).click()
  await expect(afterSales.getByText('退款回执', { exact: true })).toBeVisible()
  await expect(afterSales.getByText('已退款', { exact: true })).toBeVisible()
  expect((await order()).status).toBe('REFUNDED')
  await page.getByLabel('售后状态').selectOption('REFUNDED')
  await findRecord(page, '售后列表', caseLabel)
  await page.screenshot({
    path: testInfo.outputPath('refund-receipt.png'),
    fullPage: true,
    animations: 'disabled',
  })
  const before = writes.slice()

  expect(before.filter((path) => path.endsWith('/refund'))).toHaveLength(1)
  expect(before.filter((path) => path.endsWith('/refund-proposals'))).toHaveLength(1)
  expect(before.filter((path) => path.endsWith('/confirmations'))).toHaveLength(1)
  await page.reload()
  await expect(page.getByRole('heading', { name: '登录后继续' })).toBeVisible()
  await login(page, 'merchant')
  await openOrder(page, id)
  await expect(
    page.getByRole('region', { name: '订单详情' }).getByText('已退款', { exact: true }),
  ).toBeVisible()
  expect(writes).toEqual(before)
  expect(consoleMessages.some((message) => /eyJ[\w-]+\.[\w-]+\.[\w-]+/.test(message))).toBe(false)
})

test('a stale shipment shows a conflict and refreshes the server state', async ({
  page,
  request,
}) => {
  const buyer = await auth(request, 'buyer2')
  const { order } = await orderFixture(request, buyer)
  const paid = await order()
  await login(page, 'merchant')
  const detail = await openOrder(page, paid.id)
  await expect(detail.getByRole('button', { name: '发货', exact: true })).toBeVisible()
  await post(request, await auth(request, 'merchant'), `/merchant/orders/${paid.id}/ship`, {
    expected_version: paid.version,
  })
  await detail.getByRole('button', { name: '发货', exact: true }).click()
  await expect(detail.getByRole('alert')).toContainText('版本已变化')
  await expect(detail.getByRole('button', { name: '确认送达' })).toBeVisible()
  await expect(detail.getByRole('button', { name: '发货', exact: true })).toHaveCount(0)
})

test('buyer cannot navigate to or request merchant features', async ({ page, request }) => {
  await login(page, 'buyer1')
  await expect(page.getByRole('link', { name: '商家工作台' })).toHaveCount(0)
  await page.goto('/merchant')
  await page.getByRole('link', { name: '去登录' }).click()
  await page.getByLabel('账号', { exact: true }).fill('buyer1')
  await page.getByLabel('密码', { exact: true }).fill(password)
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await expect(page.getByRole('heading', { name: '仅商家可访问' })).toBeVisible()
  const response = await request.get(api + '/merchant/orders', {
    headers: await auth(request, 'buyer1'),
  })
  expect(response.status()).toBe(403)
})
