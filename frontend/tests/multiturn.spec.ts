import { test, expect, type Page, type APIRequestContext } from '@playwright/test'
import { mkdir, writeFile } from 'node:fs/promises'
import path from 'node:path'
import { API_ORIGIN } from './environment'

const key = { 'X-E2E-Key': 'agentmall-local-e2e' }
const evidence = path.resolve(process.env.AGENTMALL_MULTITURN_EVIDENCE_DIR ?? 'test-results/multiturn')
async function control(request: APIRequestContext, route: string, data?: object) {
  const response = data === undefined ? await request.get(API_ORIGIN + '/__test' + route, { headers: key })
    : await request.post(API_ORIGIN + '/__test' + route, { headers: key, data })
  expect(response.ok(), await response.text()).toBeTruthy()
  return response.json()
}
async function login(page: Page, restored = false) {
  if (restored) await page.getByRole('link', { name: '去登录' }).click()
  else await page.goto('/login')
  await page.getByLabel('账号', { exact: true }).fill('buyer1')
  await page.getByLabel('密码', { exact: true }).fill('AgentMall-demo-2026!')
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await expect(page.getByRole('button', { name: '退出登录' })).toBeVisible()
}
async function create(page: Page, mode = 'multi') {
  await login(page)
  await page.locator('a[href="/agent/workspace"]').first().click()
  await page.getByLabel('运行模式').selectOption(mode)
  await page.getByRole('button', { name: '创建 Thread' }).click()
  await expect(page.getByTestId('context-version')).toContainText('上下文版本 0')
}
async function turn(page: Page, text: string, target = 'COMPLETED') {
  await page.getByLabel('本次任务').fill(text)
  await page.getByRole('button', { name: '启动新 Run' }).click()
  await expect(page.getByTestId('run-status')).toHaveText(target)
  if (target === 'COMPLETED') await expect(page.getByRole('button', { name: '启动新 Run' })).toBeEnabled()
}
async function capture(page: Page, request: APIRequestContext, name: string) {
  await mkdir(evidence, { recursive: true })
  const facts = await control(request, '/facts')
  await writeFile(path.join(evidence, name + '.json'), JSON.stringify(facts, null, 2))
  await page.screenshot({ path: path.join(evidence, name + '.png'), fullPage: true, animations: 'disabled' })
  return facts
}
test.beforeEach(async ({ request, page }) => {
  await control(request, '/reset', {})
  await control(request, '/sdk-mode', { program: 'context' })
  await page.route('**/*', route => new URL(route.request().url()).hostname === '127.0.0.1' ? route.continue() : route.abort())
})
test.afterEach(async ({ request }, info) => {
  const f = await control(request, '/facts')
  await mkdir(evidence, { recursive: true })
  await writeFile(path.join(evidence, info.title.replace(/[^a-zA-Z0-9]+/g, '-') + '-state.json'), JSON.stringify({ status: info.status, facts: f }, null, 2))
  expect(f.real_model_calls).toBe(0)
  expect(f.provider_http_requests).toBe(0)
  expect(f.blocked_external_attempts).toBe(0)
})
for (const mode of ['multi', 'single']) test(`multiturn: ${mode} three turns, relogin, independent confirmation`, async ({ page, request }) => {
  await create(page, mode)
  await turn(page, '推荐一款300元以内静音键盘')
  await expect(page.getByTestId('context-preferences')).toContainText('300.00')
  await turn(page, '改成无线的，预算提高到400元')
  await expect(page.getByTestId('context-preferences')).toContainText('400.00')
  await expect(page.getByTestId('context-preferences')).toContainText('无线')
  await expect(page.getByTestId('numbered-candidate')).toHaveCount(3)
  const before = await capture(page, request, `${mode}-second-turn`)
  const target = before.candidate_set_rows.at(-1).items[1].id
  const url = page.url()
  await page.reload()
  await login(page, true)
  await expect(page).toHaveURL(url)
  await expect(page.getByTestId('numbered-candidate')).toHaveCount(3)
  await turn(page, '就买第二款，一件，送演示宿舍', 'WAITING_INPUT')
  const waiting = await capture(page, request, `${mode}-waiting`)
  expect(waiting.orders).toBe(0)
  expect(waiting.proposal_rows).toHaveLength(1)
  expect(waiting.proposal_rows[0].canonical_payload.items[0].product_id).toBe(target)
  await page.getByRole('button', { name: '批准并继续工作流' }).click()
  await expect(page.getByTestId('run-status')).toHaveText('COMPLETED')
  const f = await capture(page, request, `${mode}-completed`)
  expect(f.orders).toBe(1)
  expect(f.order_rows[0].status).toBe('PENDING_PAYMENT')
  expect(f.payment_rows).toHaveLength(0)
  expect(f.confirmation_rows).toHaveLength(1)
  expect(f.run_rows).toHaveLength(3)
  expect(f.checkpoint_rows).toBeGreaterThan(0)
  expect(f.run_event_rows.some((e: {event_type: string}) => e.event_type === 'tool')).toBe(true)
})
test('multiturn: explicit preference clearing uses no model request', async ({ page, request }) => {
  await create(page)
  await turn(page, '推荐300元以内无线静音键盘')
  const before = await control(request, '/facts')
  await page.getByRole('button', { name: '清除预算', exact: true }).click()
  await expect(page.getByTestId('context-preferences')).toContainText('预算：未指定')
  await expect(page.getByTestId('numbered-candidate')).toHaveCount(0)
  const after = await control(request, '/facts')
  expect(after.sdk.wire_requests).toBe(before.sdk.wire_requests)
  expect(after.context_mutation_rows).toHaveLength(1)
  expect(after.orders).toBe(0)
})
test('multiturn: lost start response reconciles one memory update and one Run', async ({ page, request }) => {
  await create(page)
  let dropped = false
  await page.route('**/agent/threads/*/runs', async route => {
    if (dropped) return route.continue()
    dropped = true
    await route.fetch()
    await route.abort('timedout')
  })
  await turn(page, '推荐300元以内静音键盘')
  await expect(page.getByTestId('numbered-candidate')).toHaveCount(3)
  const f = await capture(page, request, 'lost-start-response')
  expect(dropped).toBe(true)
  expect(f.run_rows).toHaveLength(1)
  expect(f.thread_context_rows[0].version).toBe(2)
  expect(f.candidate_set_rows).toHaveLength(1)
})
test('multiturn: stale browser cannot reinterpret the old second candidate', async ({ page, request }) => {
  await create(page)
  await turn(page, '推荐400元以内无线静音键盘')
  const f = await control(request, '/facts')
  const tid = f.thread_context_rows[0].thread_id
  const auth = await request.post(API_ORIGIN + '/api/v1/auth/login', { data: { login: 'buyer1', password: 'AgentMall-demo-2026!' } })
  const response = await request.patch(API_ORIGIN + `/api/v1/agent/threads/${tid}/context`, {
    headers: { Authorization: 'Bearer ' + (await auth.json()).access_token },
    data: { request_id: crypto.randomUUID(), expected_version: f.thread_context_rows[0].version,
      operations: [{ op: 'REPLACE', field: 'max_price_cents', value: 30000 }] },
  })
  expect(response.ok()).toBeTruthy()
  await page.getByLabel('本次任务').fill('就买第二款，一件，送演示宿舍')
  await page.getByRole('button', { name: '启动新 Run' }).click()
  await expect(page.getByRole('alert')).toContainText('STALE_CONTEXT')
  await expect(page.getByLabel('本次任务')).toHaveValue('')
  expect((await control(request, '/facts')).proposals).toBe(0)
})
test('multiturn: delisted candidate requires new search and never creates proposal', async ({ page, request }) => {
  await create(page)
  await turn(page, '推荐400元以内无线静音键盘')
  const f = await control(request, '/facts')
  await control(request, '/delist-product', { product_id: f.candidate_set_rows[0].items[1].id })
  await page.getByLabel('本次任务').fill('就买第二款，一件，送演示宿舍')
  await page.getByRole('button', { name: '启动新 Run' }).click()
  await expect(page.getByRole('alert').filter({ hasText: 'STALE_CANDIDATES' })).toHaveCount(1)
  expect((await control(request, '/facts')).proposals).toBe(0)
})
test('multiturn: inspection has no purchase intent and history is recoverable', async ({ page, request }) => {
  await create(page)
  await turn(page, '推荐400元以内无线静音键盘')
  await turn(page, '第二款怎么样')
  await expect(page.locator('summary').filter({ hasText: '历史 Run' })).toHaveCount(1)
  await page.locator('summary').filter({ hasText: '历史 Run' }).click()
  const f = await capture(page, request, 'inspection-history')
  expect(f.proposals).toBe(0)
  expect(f.orders).toBe(0)
  expect(f.run_rows).toHaveLength(2)
})
