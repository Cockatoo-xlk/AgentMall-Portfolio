import { test, expect } from '@playwright/test'
import type { Page, APIRequestContext } from '@playwright/test'
import { API_ORIGIN } from './environment'
import { mkdir, writeFile } from 'node:fs/promises'
import path from 'node:path'
const headers = { 'X-E2E-Key': 'agentmall-local-e2e' }
async function control(request: APIRequestContext, route: string, data?: object) {
  const r =
    data === undefined
      ? await request.get(API_ORIGIN + '/__test' + route, { headers })
      : await request.post(API_ORIGIN + '/__test' + route, { headers, data })
  expect(r.ok(), await r.text()).toBeTruthy()
  return r.json()
}
async function workspace(page: Page) {
  await page.goto('/login')
  await page.getByLabel('账号', { exact: true }).fill('buyer1')
  await page.getByLabel('密码', { exact: true }).fill('AgentMall-demo-2026!')
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await expect(page.getByRole('button', { name: '退出登录' })).toBeVisible()
  await page.locator('a[href="/agent/workspace"]').first().click()
  await page.getByRole('button', { name: '创建 Thread' }).click()
  await expect(page.getByTestId('thread-id')).toBeVisible()
  await page.getByLabel('本次任务').fill('帮我找一款300元以内的静音键盘准备购买，送演示宿舍')
  await page.getByRole('button', { name: '启动新 Run' }).click()
  await expect(page.getByTestId('run-status')).toHaveText('WAITING_INPUT')
}
test.beforeEach(async ({ page, request }) => {
  await control(request, '/reset', {})
  await page.route('**/*', (r) =>
    new URL(r.request().url()).hostname === '127.0.0.1' ? r.continue() : r.abort(),
  )
})
test.afterEach(async ({ request }) => {
  const f = await control(request, '/facts')
  expect(f.real_model_calls).toBe(0)
  expect(f.provider_http_requests).toBe(0)
  expect(f.blocked_external_attempts).toBe(0)
})
test('expiry: browser wall clock skew does not expire snapshot; deadline only GETs server', async ({
  page,
  request,
}) => {
  await page.clock.install({ time: new Date('2099-01-01T00:00:00Z') })
  await workspace(page)
  await expect(page.getByTestId('provider-mode')).toContainText('Fixture')
  await expect(page.getByTestId('proposal-countdown')).not.toContainText('UNKNOWN')
  await expect(
    page.getByRole('button', { name: '批准并继续工作流', exact: true }),
  ).toBeEnabled()
  const before = await control(request, '/facts')
  expect(before.orders).toBe(0)
  const pid = before.run_rows[0].pending_confirmation.proposal_id
  let writes = 0
  page.on('request', (r) => {
    if (
      r.method() === 'POST' &&
      /\/(confirmations|resume|runs)$/.test(new URL(r.url()).pathname)
    )
      writes++
  })
  await control(request, '/expire', { proposal_id: pid })
  await page.clock.fastForward(301000)
  await expect(page.getByText('提案已过期，需要新提案和重新确认。')).toBeVisible()
  await expect(page.getByRole('button', { name: '批准并继续工作流', exact: true })).toHaveCount(
    0,
  )
  const after = await control(request, '/facts')
  expect(writes).toBe(0)
  expect(after.proposals).toBe(before.proposals)
  expect(after.run_rows).toHaveLength(1)
  expect(after.orders).toBe(0)
  expect(after.confirmations).toBe(0)
  const out = path.resolve(
    process.env.AGENTMALL_DEMO_READINESS_EVIDENCE_DIR ?? 'test-results/demo-readiness',
  )
  await mkdir(out, { recursive: true })
  await page.screenshot({ path: path.join(out, 'expired-fixture.png'), fullPage: true })
  await writeFile(path.join(out, 'expired-state.json'), JSON.stringify(after, null, 2))
})
test('expiry: missing server time stays UNKNOWN without client-clock authorization', async ({
  page,
  request,
}) => {
  await page.clock.setFixedTime(new Date('2099-01-01T00:00:00Z'))
  await page.route('**/api/v1/proposals/*', async (route) => {
    const response = await route.fetch()
    const json = await response.json()
    delete json.server_time
    const headers = { ...response.headers() }
    delete headers['x-server-time']
    await route.fulfill({ response, json, headers })
  })
  await workspace(page)
  await expect(page.getByTestId('proposal-countdown')).toContainText('UNKNOWN')
  await expect(page.getByTestId('proposal-countdown')).toContainText('不会使用本机时钟决定授权')
  await expect(
    page.getByRole('button', { name: '批准并继续工作流', exact: true }),
  ).toBeEnabled()
  const f = await control(request, '/facts')
  expect(f.orders).toBe(0)
  expect(f.confirmations).toBe(0)
  expect(f.run_rows).toHaveLength(1)
})
test('expiry: deadline read failure is uncertain, no auto quote or decision loop', async ({
  page,
  request,
}) => {
  await page.clock.install()
  await workspace(page)
  await expect(page.getByTestId('proposal-countdown')).not.toContainText('UNKNOWN')
  let gets = 0
  await page.route('**/api/v1/proposals/*', async (route) => {
    gets++
    await route.abort('failed')
  })
  await page.clock.fastForward(301000)
  await expect(page.getByTestId('workflow-confirmation').getByRole('alert')).toBeVisible()
  await expect(page.getByText('提案已过期，需要新提案和重新确认。')).toHaveCount(0)
  await page.clock.fastForward(30000)
  expect(gets).toBe(1)
  const f = await control(request, '/facts')
  expect(f.orders).toBe(0)
  expect(f.confirmations).toBe(0)
  expect(f.proposals).toBe(1)
  expect(f.run_rows).toHaveLength(1)
})
