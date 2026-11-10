import { mkdir } from 'node:fs/promises'
import path from 'node:path'
import { expect, test } from '@playwright/test'
import { API_ORIGIN } from './environment'

test('evaluation studio presents paired results and filters diagnostic details without business writes', async ({
  page,
  request,
}) => {
  const readFacts = async () => {
    const response = await request.get(`${API_ORIGIN}/__test/facts`, {
      headers: { 'X-E2E-Key': 'agentmall-local-e2e' },
    })
    expect(response.ok()).toBe(true)
    const { orders, proposals, run_rows, case_rows, payment_rows, refund_rows } =
      await response.json()
    return {
      orders,
      proposals,
      run_rows,
      case_rows,
      payment_rows,
      refund_rows,
    }
  }
  const before = await readFacts()
  const businessRequests: string[] = []
  page.on('request', (req) => {
    if (new URL(req.url()).pathname.startsWith('/api/v1/')) businessRequests.push(req.method())
  })
  await page.setViewportSize({ width: 1440, height: 960 })
  await page.goto('/engineering/evals')
  await expect(page.getByRole('heading', { name: 'Agent Evaluation Studio' })).toBeVisible()
  const overview = page.locator('#eval-overview')
  await expect(overview.getByText('9 / 9 个计划 Episode')).toHaveCount(2)
  await expect(overview.getByText('平台账单 NOT_APPLICABLE')).toHaveCount(2)
  await expect(page.getByText('Fixture · 离线评测', { exact: true })).toBeVisible()
  await expect(page.getByText('历史 Live · 已审查汇总', { exact: true })).toBeVisible()
  const screenshots = process.env.AGENTMALL_STUDIO_SCREENSHOTS
  if (screenshots) {
    await mkdir(screenshots, { recursive: true })
    await page.screenshot({
      path: path.join(screenshots, '01-overview.png'),
      animations: 'disabled',
    })
  }
  const explorer = page.locator('#eval-explorer')
  await explorer.getByLabel('场景类别').selectOption('B2')
  await explorer.getByLabel('Agent 架构').selectOption('multi')
  await explorer.getByLabel('Run 终态').selectOption('PARTIAL')
  await explorer.getByLabel('Task ID').fill('B2_03')
  await expect(explorer.locator('details')).toHaveCount(1)
  await explorer.getByText('eval_dev_B2_03', { exact: true }).click()
  await expect(explorer.getByText('已知业务副作用 · 新增记录')).toBeVisible()
  await expect(explorer.locator('dl').filter({ hasText: '售后申请' })).toContainText('售后申请1')
  await expect(explorer.getByText('Oracle 通过')).toBeVisible()
  await explorer.getByLabel('Oracle 判定').selectOption('failed')
  await expect(explorer.getByText('没有匹配的记录。')).toBeVisible()

  await explorer.getByLabel('证据来源').selectOption('historical')
  await explorer.getByText('eval_dev_B2_01', { exact: true }).click()
  await expect(explorer.getByText('HANDOFF_CONSTRAINT_CHANGED', { exact: true })).toBeVisible()
  await expect(explorer.getByText('Oracle 未通过', { exact: true })).toBeVisible()
  await expect(
    explorer.locator('details[open]').getByText('UNKNOWN', { exact: true }).first(),
  ).toBeVisible()
  if (screenshots) {
    await explorer.screenshot({
      path: path.join(screenshots, '02-historical-failure.png'),
      animations: 'disabled',
    })
  }
  expect(businessRequests).toEqual([])
  expect(await readFacts()).toEqual(before)
})

test('evaluation studio is responsive and rejects incompatible static reports', async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 })
  const asset = '**/evals/studio-v1.json'
  await page.route(asset, (route) => route.fulfill({ json: { version: 99 } }))
  await page.goto('/engineering/evals')
  await expect(page.getByRole('alert')).toContainText('评测报告不可用')
  await page.unroute(asset)
  await page.getByRole('button', { name: '重新读取' }).click()
  await expect(page.getByRole('heading', { name: '执行总览' })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390)
})
