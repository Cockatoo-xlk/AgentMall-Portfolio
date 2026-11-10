import { expect, test } from '@playwright/test'
import type { APIRequestContext, Page } from '@playwright/test'
import { API_ORIGIN } from './environment'

async function control(request: APIRequestContext, route: string, body?: object) {
  const headers = { 'X-E2E-Key': 'agentmall-local-e2e' }
  const response = body
    ? await request.post(API_ORIGIN + '/__test' + route, { headers, data: body })
    : await request.get(API_ORIGIN + '/__test' + route, { headers })
  expect(response.ok(), await response.text()).toBe(true)
  return response.json()
}

async function login(page: Page, name: string) {
  await page.getByLabel('账号', { exact: true }).fill(name)
  await page.getByLabel('密码', { exact: true }).fill('AgentMall-demo-2026!')
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await expect(page.getByRole('button', { name: '退出登录' })).toBeVisible()
}

test('V2 RC connects intent routing, live progress, merchant fulfillment and read-only evaluation', async ({ page, request }) => {
  await control(request, '/reset', {})
  await control(request, '/sdk-mode', { program: 'recommend', delay_ms: 1000 })
  await page.goto('/login')
  await login(page, 'buyer1')
  await page.getByRole('link', { name: '工作流', exact: true }).click()
  await page.getByRole('button', { name: '创建 Thread' }).click()
  await page.getByLabel('本次任务').fill('推荐300元以内的静音键盘，不要购买。')
  await page.getByRole('button', { name: '启动新 Run' }).click()
  await expect(page.getByTestId('run-status')).toHaveText('RUNNING')
  await expect(page.getByTestId('run-event').filter({ hasText: 'Specialist Handoff' })).toHaveCount(1)
  await expect(page.getByTestId('run-status')).toHaveText('COMPLETED')
  const recommended = await control(request, '/facts')
  expect(recommended.orders).toBe(0)
  expect(recommended.confirmation_rows).toHaveLength(0)
  expect(recommended.run_event_rows.some((event: { event_type: string; payload_summary: { target?: string } }) =>
    event.event_type === 'handoff' && event.payload_summary.target === 'order',
  )).toBe(false)

  await control(request, '/sdk-mode', { program: 'purchase' })
  await page.getByLabel('本次任务').fill('帮我找一款300元以内静音键盘准备购买，送演示宿舍')
  await page.getByRole('button', { name: '启动新 Run' }).click()
  await expect(page.getByTestId('run-status')).toHaveText('WAITING_INPUT')
  expect((await control(request, '/facts')).orders).toBe(0)
  await page.getByRole('button', { name: '批准并继续工作流' }).click()
  await expect(page.getByTestId('run-status')).toHaveText('COMPLETED')
  const purchased = await control(request, '/facts')
  expect(purchased.orders).toBe(1)
  expect(purchased.payment_rows).toHaveLength(0)
  const order = purchased.order_rows[0].id
  await page.getByTestId('resource-order').getByRole('link', { name: '查看真实订单' }).click()
  await page.getByRole('button', { name: '模拟付款', exact: true }).click()
  await page.getByRole('button', { name: '批准并模拟付款', exact: true }).click()
  await expect(page.getByTestId('payment-receipt')).toContainText('SUCCEEDED')

  await page.getByRole('button', { name: '退出登录' }).click()
  await page.getByRole('link', { name: '去登录' }).click()
  await login(page, 'merchant')
  await page.getByRole('link', { name: '商家工作台', exact: true }).click()
  await page.getByRole('button', { name: `查看订单 ${order}`, exact: true }).click()
  const detail = page.getByRole('region', { name: '订单详情' })
  await detail.getByRole('button', { name: '发货', exact: true }).click()
  await detail.getByRole('button', { name: '确认送达', exact: true }).click()
  await expect(detail.getByText('已签收', { exact: true })).toBeVisible()
  const beforeStudio = await control(request, '/facts')
  await page.getByRole('link', { name: '评测工作台', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Agent Evaluation Studio' })).toBeVisible()
  const afterStudio = await control(request, '/facts')
  expect(afterStudio.order_rows).toEqual(beforeStudio.order_rows)
  expect(afterStudio.confirmation_rows).toEqual(beforeStudio.confirmation_rows)
  expect(afterStudio.payment_rows).toEqual(beforeStudio.payment_rows)
  expect(afterStudio.order_rows).toEqual([expect.objectContaining({ id: order, status: 'DELIVERED' })])
  expect(afterStudio.real_model_calls).toBe(0)
  expect(afterStudio.provider_http_requests).toBe(0)
})
