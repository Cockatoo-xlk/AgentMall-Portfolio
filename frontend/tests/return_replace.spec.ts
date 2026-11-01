import { test, expect } from '@playwright/test'
import { API_ORIGIN } from './environment'
import type { Page, APIRequestContext } from '@playwright/test'
import { mkdir, writeFile } from 'node:fs/promises'
import path from 'node:path'
import type { Run, RunEvent } from '../src/api/agentWorkflow'
import type { Order } from '../src/api/types'
const API = API_ORIGIN + '/api/v1'
const key = { 'X-E2E-Key': 'agentmall-local-e2e' }
const password = 'AgentMall-demo-2026!'
const evidence = path.resolve(process.env.AGENTMALL_WORKFLOW_EVIDENCE_DIR ?? 'evidence/t10')
interface Row {
  id: string
  status: string
  proposal_id: string
  order_id: string
  decision: string
  confirmation_id: string
  consumed_at: string | null
  result_ref: string | null
  version: number
  resolution: string | null
}
interface Facts {
  schema: string
  checkpoint_schema: string
  orders: number
  proposals: number
  confirmations: number
  reserved: number
  receipts: number
  events: number
  provider_http_requests: number
  real_model_calls: number
  blocked_external_attempts: number
  checkpoint_rows: number
  checkpoints: {
    run_id: string
    graph: { pending_action: { proposal_id: string } | null; next: string; handled: string[] }
  }[]
  run_rows: Run[]
  run_event_rows: (RunEvent & { run_id: string })[]
  order_rows: Row[]
  case_rows: Row[]
  refund_rows: Row[]
  ticket_rows: Row[]
  proposal_rows: Row[]
  confirmation_rows: Row[]
  event_rows: unknown[]
}
async function control(request: APIRequestContext, endpoint: string, data?: object) {
  const response =
    data === undefined
      ? await request.get(`${API_ORIGIN}/__test${endpoint}`, { headers: key })
      : await request.post(`${API_ORIGIN}/__test${endpoint}`, { headers: key, data })
  expect(response.ok()).toBeTruthy()
  return response.json()
}
const facts = (request: APIRequestContext): Promise<Facts> => control(request, '/facts')
async function auth(request: APIRequestContext, login = 'buyer1') {
  const result = await request.post(`${API}/auth/login`, { data: { login, password } })
  expect(result.ok()).toBeTruthy()
  return { Authorization: `Bearer ${(await result.json()).access_token}` }
}
async function post(
  request: APIRequestContext,
  headers: Record<string, string>,
  url: string,
  data: object,
) {
  const r = await request.post(API + url, {
    headers: { ...headers, 'Idempotency-Key': crypto.randomUUID() },
    data,
  })
  expect(r.ok(), await r.text()).toBeTruthy()
  return r.json()
}
async function get(request: APIRequestContext, headers: Record<string, string>, url: string) {
  const r = await request.get(API + url, { headers })
  expect(r.ok()).toBeTruthy()
  return r.json()
}
async function seedOrder(request: APIRequestContext, delivered = true): Promise<Order> {
  const buyer = await auth(request)
  const products = await get(request, buyer, '/products?category=keyboard')
  const product = products.items[0].id
  let p = await post(request, buyer, '/checkout/proposals', {
    request_id: crypto.randomUUID(),
    proposal_slot: 'fixture_order',
    address_label: 'demo_dorm',
    items: [{ product_id: product, quantity: 1 }],
  })
  let c = await post(request, buyer, `/proposals/${p.proposal_id}/confirmations`, {
    decision: 'approve',
  })
  const receipt = await post(request, buyer, '/orders', {
    proposal_id: p.proposal_id,
    confirmation_id: c.confirmation_id,
  })
  let order = await get(request, buyer, `/orders/${receipt.order_id}`)
  if (!delivered) return order
  p = await post(request, buyer, `/orders/${order.id}/payment-proposals`, {
    request_id: crypto.randomUUID(),
    expected_version: order.version,
  })
  c = await post(request, buyer, `/proposals/${p.proposal_id}/confirmations`, {
    decision: 'approve',
  })
  await post(request, buyer, `/orders/${order.id}/mock-payments`, {
    proposal_id: p.proposal_id,
    confirmation_id: c.confirmation_id,
  })
  order = await get(request, buyer, `/orders/${order.id}`)
  const merchant = await auth(request, 'merchant')
  for (const event of ['ship', 'deliver'])
    order = await post(request, merchant, `/merchant/orders/${order.id}/${event}`, {
      expected_version: order.version,
    })
  return order
}
async function login(page: Page, fromCurrent = false, user = 'buyer1') {
  if (fromCurrent) await page.getByRole('link', { name: '去登录' }).click()
  else await page.goto('/login')
  await page.getByLabel('账号', { exact: true }).fill(user)
  await page.getByLabel('密码', { exact: true }).fill(password)
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await expect(page.getByRole('button', { name: '退出登录' })).toBeVisible()
}
const purchase = '找一款300元以内静音键盘准备购买，送演示宿舍'
async function workspace(page: Page, message = purchase, mode = 'multi') {
  await login(page)
  await page.locator('a[href="/agent/workspace"]').first().click()
  await page.getByLabel('运行模式').selectOption(mode)
  await page.getByRole('button', { name: '创建 Thread' }).click()
  await expect(page.getByTestId('thread-id')).toBeVisible()
  await page.getByLabel('本次任务').fill(message)
  const response = page.waitForResponse(
    (r) => r.request().method() === 'POST' && r.url().endsWith('/runs'),
  )
  await page.getByRole('button', { name: '启动新 Run' }).click()
  await response
  await expect(page.getByTestId('run-status')).toBeVisible()
}
async function approve(page: Page) {
  await page.getByRole('button', { name: '批准并继续工作流' }).click()
}
async function capture(page: Page, request: APIRequestContext, name: string) {
  await mkdir(evidence, { recursive: true })
  const f = await facts(request)
  await writeFile(path.join(evidence, name + '.json'), JSON.stringify(f, null, 2))
  await page.evaluate(() => window.scrollTo(0, 0))
  await page.screenshot({
    path: path.join(evidence, name + '.png'),
    fullPage: true,
    animations: 'disabled',
  })
}
test.beforeEach(async ({ page, request }) => {
  await mkdir(evidence, { recursive: true })
  await control(request, '/reset', {})
  await page.route('**/*', (route) =>
    new URL(route.request().url()).hostname === '127.0.0.1' ? route.continue() : route.abort(),
  )
  // The browser workflow must never submit a second domain action independently.
  page.on('request', (r) => {
    if (r.method() === 'POST')
      expect(new URL(r.url()).pathname).not.toMatch(/^\/api\/v1\/(orders|after-sales)$/)
  })
})
test.afterEach(async ({ request }, testInfo) => {
  const f = await facts(request)
  expect(f.schema).toMatch(/^test_[0-9a-f]{32}$/)
  expect(f.checkpoint_schema).toMatch(/^cp_[0-9a-f]{32}$/)
  expect(f.provider_http_requests).toBe(0)
  expect(f.real_model_calls).toBe(0)
  expect(f.blocked_external_attempts).toBe(0)
  await mkdir(path.join(evidence, 'final-states'), { recursive: true })
  await writeFile(
    path.join(evidence, 'final-states', testInfo.title.replace(/[^a-zA-Z0-9]+/g, '-') + '.json'),
    JSON.stringify({ test: testInfo.title, status: testInfo.status, facts: f }, null, 2),
  )
})
test('return_replace: real handoff, waiting, approval, timeline and checkpoint agree with SQL', async ({
  page,
  request,
}) => {
  await workspace(page)
  await expect(page.getByTestId('run-status')).toHaveText('WAITING_INPUT')
  const before = await facts(request)
  expect(before.orders).toBe(0)
  expect(before.run_rows[0].result?.execution_mode).toBe('FIXTURE')
  await expect(page.getByTestId('run-summary')).toContainText('Fixture · Fake Model')
  expect(before.checkpoint_rows).toBeGreaterThan(0)
  expect(before.checkpoints[0].graph.pending_action?.proposal_id).toBe(
    before.run_rows[0].pending_confirmation?.proposal_id,
  )
  await expect(page.getByText('Specialist Handoff', { exact: true }).first()).toBeVisible()
  await approve(page)
  await expect(page.getByTestId('run-status')).toHaveText('COMPLETED')
  await expect(page.getByTestId('resource-order')).toContainText('PENDING_PAYMENT')
  const after = await facts(request)
  expect(after.orders).toBe(1)
  expect(after.confirmations).toBe(1)
  expect(after.receipts).toBe(1)
  expect(after.events).toBe(1)
  expect(after.checkpoints[0].graph.handled).toEqual([
    before.run_rows[0].pending_confirmation!.proposal_id,
  ])
  await expect(page.getByTestId('run-event')).toHaveCount(after.run_event_rows.length)
  const seq = await page
    .getByTestId('run-event')
    .evaluateAll((rows) => rows.map((r) => Number(r.getAttribute('data-seq'))))
  expect(seq).toEqual(after.run_event_rows.map((r) => r.seq))
  expect(
    after.run_event_rows.some(
      (e) => e.event_type === 'model_end' && e.payload_summary.usage === 'UNKNOWN',
    ),
  ).toBe(true)
  const headers = await auth(request)
  const trace = await get(request, headers, `/agent/runs/${after.run_rows[0].id}/trace?limit=100`)
  expect(trace.items.length).toBe(after.run_event_rows.length)
  await writeFile(path.join(evidence, 'redacted-trace.json'), JSON.stringify(trace, null, 2))
  await capture(page, request, 'workflow-completed')
})
test('return_replace: rejection is recorded and creates no order', async ({ page, request }) => {
  await workspace(page)
  await page.getByRole('button', { name: '拒绝并继续工作流' }).click()
  await expect(page.getByText(/用户已拒绝/)).toBeVisible()
  const f = await facts(request)
  expect(f.orders).toBe(0)
  expect(f.confirmations).toBe(1)
  expect(f.confirmation_rows[0].decision).toBe('reject')
  expect(f.events).toBe(0)
})
test('return_replace: two independent return and checkout interrupts cannot reuse approval', async ({
  page,
  request,
}) => {
  const order = await seedOrder(request)
  await control(request, '/workflow-mode', { mode: 'return_replace' })
  await workspace(
    page,
    `订单${order.id}质量问题想退掉，再帮我推荐一款500元以内静音键盘，准备购买，送演示宿舍。`,
  )
  await expect(page.getByRole('heading', { name: '确认退货申请' })).toBeVisible()
  const first = (await facts(request)).run_rows[0]
  const resumes: Record<string, string>[] = []
  page.on('request', (r) => {
    if (r.url().endsWith('/resume')) resumes.push(r.postDataJSON())
  })
  await approve(page)
  await expect(page.getByRole('heading', { name: '确认购买快照' })).toBeVisible()
  const middle = await facts(request)
  expect(middle.case_rows).toHaveLength(1)
  expect(middle.orders).toBe(1)
  expect(middle.refund_rows).toHaveLength(0)
  expect(middle.run_rows[0].pending_confirmation!.interrupt_id).not.toBe(
    first.pending_confirmation!.interrupt_id,
  )
  const buyer = await auth(request)
  await post(request, buyer, `/agent/threads/${first.thread_id}/resume`, resumes[0])
  expect((await facts(request)).orders).toBe(1)
  await approve(page)
  await expect(page.getByTestId('run-status')).toHaveText('COMPLETED')
  expect(resumes).toHaveLength(2)
  expect(resumes[0].confirmation_id).not.toBe(resumes[1].confirmation_id)
  expect(resumes[0].request_id).not.toBe(resumes[1].request_id)
  const f = await facts(request)
  expect(f.orders).toBe(2)
  expect(f.case_rows).toHaveLength(1)
  expect(f.refund_rows).toHaveLength(0)
  expect(f.run_rows[0].pending_confirmation).toBeNull()
  await capture(page, request, 'return-replace-completed')
})
test('return_replace: refresh requires login and rebuilds known Thread from seq zero', async ({
  page,
  request,
}) => {
  await workspace(page)
  const f = await facts(request)
  const url = page.url()
  await page.reload()
  await expect(page.getByText('登录后继续')).toBeVisible()
  await login(page, true)
  await expect(page).toHaveURL(url)
  await expect(page.getByTestId('run-status')).toHaveText('WAITING_INPUT')
  await expect(page.getByTestId('run-event')).toHaveCount(f.run_event_rows.length)
  expect(
    await page.evaluate(() => JSON.stringify({ ...localStorage, ...sessionStorage })),
  ).not.toMatch(/Bearer|access_token|eyJ/)
  await approve(page)
  await expect(page.getByTestId('resource-order')).toBeVisible()
  expect((await facts(request)).orders).toBe(1)
})
test('return_replace: duplicate clicks cause one confirmation and one order', async ({
  page,
  request,
}) => {
  await workspace(page)
  await page.getByRole('button', { name: '批准并继续工作流' }).dblclick()
  await expect(page.getByTestId('run-status')).toHaveText('COMPLETED')
  const f = await facts(request)
  expect(f.orders).toBe(1)
  expect(f.confirmations).toBe(1)
  expect(f.events).toBe(1)
})
test('return_replace: lost committed Resume response reconciles without another write', async ({
  page,
  request,
}) => {
  await workspace(page)
  let writes = 0
  await page.route('**/resume', async (route) => {
    writes++
    await route.fetch()
    await route.abort('failed')
  })
  await approve(page)
  await expect(page.getByTestId('resource-order')).toContainText('PENDING_PAYMENT')
  await expect(page.getByTestId('run-status')).toHaveText('COMPLETED')
  expect(writes).toBe(1)
  expect((await facts(request)).orders).toBe(1)
  await capture(page, request, 'lost-resume-recovered')
})
test('return_replace: unsubmitted Resume retry retains request ID after reads', async ({
  page,
  request,
}) => {
  await workspace(page)
  const ids: string[] = []
  await page.route('**/resume', async (route) => {
    ids.push(route.request().postDataJSON().request_id)
    if (ids.length === 1) await route.abort('failed')
    else await route.continue()
  })
  await approve(page)
  await expect(page.getByRole('button', { name: '核对并重试原恢复' })).toBeVisible()
  expect((await facts(request)).orders).toBe(0)
  await page.getByRole('button', { name: '核对并重试原恢复' }).click()
  await expect(page.getByTestId('run-status')).toHaveText('COMPLETED')
  expect(ids).toHaveLength(2)
  expect(ids[0]).toBe(ids[1])
  expect((await facts(request)).orders).toBe(1)
})
test('return_replace: created case survives recommendation failure; independent retry is read only', async ({
  page,
  request,
}) => {
  const order = await seedOrder(request)
  await control(request, '/workflow-mode', { mode: 'return_partial' })
  await workspace(page, `订单${order.id}质量问题想退掉，再帮我推荐一款500元以内静音键盘`)
  await approve(page)
  await expect(page.getByTestId('run-status')).toHaveText('PARTIAL')
  await expect(page.getByTestId('resource-case')).toContainText('REQUESTED')
  const before = await facts(request)
  expect(before.case_rows).toHaveLength(1)
  expect(before.refund_rows).toHaveLength(0)
  await capture(page, request, 'partial-case-retained')
  await page.getByRole('button', { name: '只重试推荐（新 Run）' }).click()
  await expect(page.getByTestId('run-status')).toHaveText('COMPLETED')
  const after = await facts(request)
  expect(after.case_rows[0].id).toBe(before.case_rows[0].id)
  expect(after.case_rows).toHaveLength(1)
  expect(after.proposals).toBe(before.proposals)
  expect(after.orders).toBe(before.orders)
  expect(after.run_rows).toHaveLength(2)
  expect(after.run_rows[1].constraints.max_price_cents).toBe(50000)
  expect(after.run_rows[1].constraints.exclude_original).toBe(true)
  const originalProducts = order.items.map((item) => item.product_id)
  const candidates = after.run_rows[1].result!.entity_refs.filter(
    (ref) => ref.kind === 'product' && ref.relation === 'replacement',
  )
  expect(candidates.length).toBeGreaterThan(0)
  expect(candidates.every((ref) => !originalProducts.includes(ref.id))).toBe(true)
})
test('return_replace: recommendation survives deterministic eligibility rejection', async ({
  page,
  request,
}) => {
  const order = await seedOrder(request, false)
  await workspace(page, `订单${order.id}质量问题想退掉，再帮我推荐一款500元以内静音键盘`)
  await expect(page.getByTestId('run-status')).toHaveText('PARTIAL')
  await expect(page.getByTestId('run-summary')).toContainText('AFTERSALES_INELIGIBLE')
  await expect(page.getByTestId('resource-product').first()).toBeVisible()
  const f = await facts(request)
  expect(f.orders).toBe(1)
  expect(f.case_rows).toHaveLength(0)
  expect(f.refund_rows).toHaveLength(0)
})
test('return_replace: human ticket state is real; RESOLVED is not refunded', async ({
  page,
  request,
}) => {
  const order = await seedOrder(request)
  await workspace(page, `订单${order.id}联系人工处理售后争议`)
  await expect(page.getByTestId('resource-ticket')).toContainText('OPEN')
  const before = await facts(request)
  expect(before.ticket_rows).toHaveLength(1)
  const ticket = before.ticket_rows[0]
  const merchant = await auth(request, 'merchant')
  const claimed = await post(request, merchant, `/merchant/tickets/${ticket.id}/claim`, {
    expected_version: ticket.version,
  })
  await post(request, merchant, `/merchant/tickets/${ticket.id}/resolve`, {
    expected_version: claimed.version,
    resolution: 'EXPLAINED',
    summary: 'Fixture 已解释公开政策，未退款。',
  })
  await page.getByTestId('resource-ticket').getByRole('button', { name: '核对最新状态' }).click()
  await expect(page.getByTestId('resource-ticket')).toContainText('RESOLVED')
  await expect(page.getByTestId('resource-ticket')).toContainText('不代表自动退款')
  expect((await facts(request)).refund_rows).toHaveLength(0)
  await capture(page, request, 'human-handoff-resolved')
})
test('return_replace: expired snapshot requires new quote and new approval', async ({
  page,
  request,
}) => {
  await workspace(page)
  const before = await facts(request)
  const pid = before.run_rows[0].pending_confirmation!.proposal_id!
  await control(request, '/expire', { proposal_id: pid })
  await page.getByRole('button', { name: '刷新提案状态' }).click()
  await expect(page.getByText('提案已过期，需要新提案和重新确认。')).toBeVisible()
  await expect(page.getByRole('button', { name: '批准并继续工作流' })).toHaveCount(0)
  await page.getByRole('button', { name: '重新请求报价' }).click()
  await page.getByLabel('本次任务').fill(purchase)
  await page.getByRole('button', { name: '启动新 Run' }).click()
  await expect(page.getByRole('button', { name: '批准并继续工作流' })).toBeVisible()
  const next = await facts(request)
  expect(next.proposals).toBe(2)
  expect(next.orders).toBe(0)
  expect(next.confirmations).toBe(0)
  expect(next.run_rows[1].pending_confirmation!.proposal_id).not.toBe(pid)
  await approve(page)
  await expect(page.getByTestId('run-status')).toHaveText('COMPLETED')
  expect((await facts(request)).orders).toBe(1)
})
test('return_replace: other buyer cannot read Thread Run Events or Trace', async ({
  page,
  request,
}) => {
  await workspace(page)
  const run = (await facts(request)).run_rows[0]
  const buyer2 = await auth(request, 'buyer2')
  for (const endpoint of [
    `/agent/threads/${run.thread_id}`,
    `/agent/runs/${run.id}/events`,
    `/agent/runs/${run.id}/trace`,
  ])
    expect((await request.get(API + endpoint, { headers: buyer2 })).status()).toBe(404)
  await page.getByRole('button', { name: '退出登录' }).click()
  await login(page, true, 'buyer2')
  await expect(page.getByRole('alert').first()).toContainText('没有访问权限')
  await expect(page.getByTestId('run-event')).toHaveCount(0)
})
test('return_replace: model disabled is explicitly displayed without business effects', async ({
  page,
  request,
}) => {
  await control(request, '/workflow-mode', { mode: 'disabled' })
  await workspace(page)
  await expect(page.getByText('MODEL_DISABLED · 模型未启用')).toBeVisible()
  const f = await facts(request)
  expect(f.orders).toBe(0)
  expect(f.proposals).toBe(0)
})
test('return_replace: mobile workspace and policy citations use real public order version', async ({
  page,
  request,
}) => {
  const order = await seedOrder(request)
  await page.setViewportSize({ width: 390, height: 844 })
  await login(page)
  await page.locator('a[href="/after-sales"]').first().click()
  await page.getByLabel('选择本人订单').selectOption(order.id)
  await expect(page.getByText('符合申请条件', { exact: false })).toBeVisible()
  await expect(page.getByTestId('policy-citation').first()).toBeVisible()
  await page.getByTestId('policy-citation').first().locator('summary').click()
  await expect(page.getByTestId('policy-citation').first()).toContainText(order.policy_version)
  expect(await page.locator('a[href^="fixture:"]').count()).toBe(0)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await capture(page, request, 'after-sales-mobile')
  await page.getByRole('link', { name: '进入工作流准备退货提案' }).click()
  await page.getByRole('button', { name: '创建 Thread' }).click()
  await expect(page.getByLabel('本次任务')).toHaveValue(new RegExp(order.id))
  await page.getByRole('button', { name: '启动新 Run' }).click()
  await expect(page.getByRole('heading', { name: '确认退货申请' })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await capture(page, request, 'workspace-mobile')
})
test('return_replace: event network failure retains prior rows and retry deduplicates', async ({
  page,
  request,
}) => {
  await workspace(page)
  const count = (await facts(request)).run_event_rows.length
  await expect(page.getByTestId('run-event')).toHaveCount(count)
  await page.route('**/events?*', (route) => route.abort('failed'), { times: 1 })
  await page.getByRole('button', { name: '刷新事件' }).click()
  await expect(page.getByText(/事件读取中断/)).toBeVisible()
  await expect(page.getByTestId('run-event')).toHaveCount(count)
  await page.getByRole('button', { name: '刷新事件' }).click()
  await expect(page.getByText(/事件读取中断/)).toHaveCount(0)
  await expect(page.getByTestId('run-event')).toHaveCount(count)
})
test('return_replace: durable single mode also requires approval', async ({ page, request }) => {
  await workspace(page, purchase, 'single')
  await expect(page.getByTestId('run-status')).toHaveText('WAITING_INPUT')
  expect((await facts(request)).orders).toBe(0)
  await approve(page)
  await expect(page.getByTestId('run-status')).toHaveText('COMPLETED')
  expect((await facts(request)).orders).toBe(1)
})

test('return_replace: business receipt survives final answer rendering failure', async ({
  page,
  request,
}) => {
  await control(request, '/workflow-mode', { mode: 'answer_failure' })
  await workspace(page)
  const ids: string[] = []
  page.on('request', (r) => {
    if (r.url().endsWith('/resume')) ids.push(r.postDataJSON().request_id)
  })
  await approve(page)
  await expect(page.getByTestId('resource-order')).toContainText('PENDING_PAYMENT')
  await expect(page.getByText(/业务已执行，工作流回答尚待核实/)).toBeVisible()
  const before = await facts(request)
  expect(before.orders).toBe(1)
  expect(before.run_rows[0].status).toBe('RUNNING')
  await capture(page, request, 'business-done-answer-failed')
  await page.getByRole('button', { name: '核对并重试原恢复' }).click()
  await expect(page.getByTestId('run-status')).toHaveText('COMPLETED')
  const after = await facts(request)
  expect(after.orders).toBe(1)
  expect(after.order_rows[0].id).toBe(before.order_rows[0].id)
  expect(after.events).toBe(1)
  expect(ids).toHaveLength(2)
  expect(ids[0]).toBe(ids[1])
})

for (const mode of ['start_interrupted', 'start_unfinalized']) {
  test(`return_replace: ${mode} survives refresh and recovers original Run by reference`, async ({
    page,
    request,
  }) => {
    await control(request, '/workflow-mode', { mode })
    await workspace(page)
    await expect(page.getByRole('button', { name: '恢复原 Run' })).toBeVisible()
    const before = await facts(request)
    await page.reload()
    await login(page, true)
    await expect(page.getByRole('button', { name: '恢复原 Run' })).toBeVisible()
    await page.getByRole('button', { name: '恢复原 Run' }).click()
    await expect(page.getByTestId('run-status')).toHaveText('WAITING_INPUT')
    expect((await facts(request)).run_rows[0].id).toBe(before.run_rows[0].id)
    await approve(page)
    await expect(page.getByTestId('run-status')).toHaveText('COMPLETED')
    const after = await facts(request)
    expect(after.run_rows).toHaveLength(1)
    expect(after.orders).toBe(1)
    await capture(page, request, mode + '-recovered')
  })
}

test('return_replace: two clarification interrupts use distinct requests and new input', async ({
  page,
  request,
}) => {
  await control(request, '/workflow-mode', { mode: 'clarify' })
  await workspace(page, '帮我准备购买静音键盘')
  const ids: Record<string, string>[] = []
  page.on('request', (r) => {
    if (r.url().endsWith('/resume')) ids.push(r.postDataJSON())
  })
  await page.getByLabel('补充信息').fill('300元以内')
  await page.getByRole('button', { name: '提交补充并 Resume' }).click()
  await expect(page.getByLabel('补充信息')).toHaveValue('')
  await page.getByLabel('补充信息').fill('一款，送演示宿舍')
  await page.getByRole('button', { name: '提交补充并 Resume' }).click()
  await expect(page.getByRole('heading', { name: '确认购买快照' })).toBeVisible()
  expect(ids).toHaveLength(2)
  expect(ids[0].interrupt_id).not.toBe(ids[1].interrupt_id)
  expect(ids[0].request_id).not.toBe(ids[1].request_id)
  expect(ids[1].clarification).toBe('一款，送演示宿舍')
  await approve(page)
  await expect(page.getByTestId('run-status')).toHaveText('COMPLETED')
  expect((await facts(request)).orders).toBe(1)
})

test('return_replace: pending start response does not hide durable running state or events', async ({
  page,
  request,
}) => {
  await control(request, '/workflow-mode', { mode: 'start_unfinalized' })
  let release!: () => void
  let fetched!: () => void
  const responseGate = new Promise<void>((resolve) => {
    release = resolve
  })
  const committed = new Promise<void>((resolve) => {
    fetched = resolve
  })
  await page.route('**/api/v1/agent/threads/*/runs', async (route) => {
    const response = await route.fetch()
    fetched()
    await responseGate
    await route.fulfill({ response })
  })
  const work = workspace(page)
  // Catch the helper's assertion immediately too, to avoid an unhandled rejection in RED.
  const finished = work.then(
    () => null,
    (error) => error,
  )
  try {
    await committed
    await expect(page.getByTestId('run-status')).toHaveText('RUNNING')
    await expect(page.getByTestId('run-event').first()).toBeVisible()
    const f = await facts(request)
    expect(f.run_rows[0].status).toBe('RUNNING')
    expect(f.orders).toBe(0)
  } finally {
    release()
    await finished
  }
  await expect(page.getByRole('button', { name: '恢复原 Run' })).toBeEnabled()
  await page.getByRole('button', { name: '恢复原 Run' }).click()
  await expect(page.getByTestId('run-status')).toHaveText('WAITING_INPUT')
})
