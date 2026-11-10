import { expect, test } from '@playwright/test'
import { mkdir } from 'node:fs/promises'
import path from 'node:path'
import { API_ORIGIN } from './environment'
const key = { 'X-E2E-Key': 'agentmall-local-e2e' }
const message = '预算5000元，帮我搭配一套居家办公设备，包括27英寸显示器、键盘、鼠标和耳机。先推荐，不要购买。'
test('bundle revisions survive stream interruption and login restore before one explicit checkout', async ({ page, request }) => {
  expect((await request.post(API_ORIGIN + '/__test/reset', { headers: key, data: {} })).ok()).toBeTruthy()
  expect((await request.post(API_ORIGIN + '/__test/sdk-mode', { headers: key, data: { program: 'bundle', delay_ms: 150 } })).ok()).toBeTruthy()
  await page.route('**/*', route => new URL(route.request().url()).hostname === '127.0.0.1' ? route.continue() : route.abort())
  async function login() {
    await page.getByLabel('账号', { exact: true }).fill('buyer1')
    await page.getByLabel('密码', { exact: true }).fill('AgentMall-demo-2026!')
    await page.getByRole('button', { name: '登录', exact: true }).click()
  }
  await page.goto('/login'); await login()
  await page.locator('a[href="/agent/workspace"]').first().click()
  await page.getByRole('button', { name: '创建 Thread' }).click()
  await page.getByLabel('本次任务').fill(message)
  await page.getByRole('button', { name: '启动新 Run' }).click()
  await expect(page.getByTestId('run-status')).toHaveText('COMPLETED')
  const before = await (await request.get(API_ORIGIN + '/__test/facts', { headers: key })).json()
  expect(before.orders).toBe(0); expect(before.proposals).toBe(0)
  const oldText = await page.getByTestId('bundle-offer').innerText()
  let interrupted = false
  await page.route('**/events/stream?*', async route => {
    if (!interrupted) { interrupted = true; await route.abort() } else await route.continue()
  })
  await page.getByLabel('本次任务').fill('显示器不要换，键盘必须支持无线连接，再加一个音箱。')
  await page.getByRole('button', { name: '启动新 Run' }).click()
  await expect(page.getByTestId('run-status')).toHaveText('COMPLETED')
  await expect(page.getByTestId('bundle-item')).toHaveCount(5)
  await expect(page.getByTestId('bundle-diff')).toContainText('重新检索')
  await expect(page.getByTestId('bundle-diff')).toContainText('保留')
  await expect(page.getByTestId('bundle-diff')).toContainText('新增')
  await expect(page.getByTestId('bundle-offer')).not.toHaveText(oldText)
  const root = process.env.AGENTMALL_BUNDLE_EVIDENCE_DIR ?? 'test-results/bundle-replanning'
  await mkdir(root, { recursive: true })
  await page.screenshot({ path: path.join(root, 'v29-revision-workspace.png'), fullPage: true })
  await page.getByRole('region', { name: '组合购物方案', exact: true }).screenshot({ path: path.join(root, 'v29-diff.png') })
  const revisionText = await page.getByTestId('bundle-offer').textContent()
  expect(revisionText).not.toBeNull()
  await page.reload(); await page.getByRole('link', { name: '去登录' }).click(); await login()
  await expect(page.getByTestId('bundle-offer')).toHaveText(revisionText!)
  await page.getByText(/历史方案（/).click()
  await expect(page.getByLabel('选择此整套方案')).toHaveCount(1)
  const after = await (await request.get(API_ORIGIN + '/__test/facts', { headers: key })).json()
  expect(after.orders).toBe(0); expect(after.proposals).toBe(0)
  await page.getByLabel('选择此整套方案').check()
  await page.getByLabel('本次任务').fill('就买修改后的这套，每样一件，送演示宿舍。')
  await page.getByRole('button', { name: '启动新 Run' }).click()
  await expect(page.getByTestId('run-status')).toHaveText('WAITING_INPUT')
  const waiting = await (await request.get(API_ORIGIN + '/__test/facts', { headers: key })).json()
  expect(waiting.orders).toBe(0); expect(waiting.proposal_rows).toHaveLength(1)
  expect(waiting.proposal_rows[0].canonical_payload.items).toHaveLength(5)
  // TEST_OPERATOR explicitly approves the immutable five-SKU snapshot.
  await page.getByRole('button', { name: '批准并继续工作流' }).click()
  await expect(page.getByTestId('run-status')).toHaveText('COMPLETED')
  await page.reload()
  const done = await (await request.get(API_ORIGIN + '/__test/facts', { headers: key })).json()
  expect(done.order_rows).toHaveLength(1)
  expect(done.order_rows[0].status).toBe('PENDING_PAYMENT')
  expect(done.payment_rows).toHaveLength(0)
  expect(done.real_model_calls).toBe(0); expect(done.provider_http_requests).toBe(0)
})
