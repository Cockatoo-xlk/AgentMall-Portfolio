import { expect, test } from '@playwright/test'
import { mkdir } from 'node:fs/promises'
import path from 'node:path'

test('real retrieval evidence compares paired pipelines, filters failures and performs no business writes', async ({ page }) => {
  const writes: string[] = []
  page.on('request', r => { if (r.url().includes('/api/v1/') && !['GET', 'HEAD'].includes(r.method())) writes.push(r.method()) })
  await page.route('**/*', route => new URL(route.request().url()).hostname === '127.0.0.1' ? route.continue() : route.abort())
  await page.goto('/engineering/evals')
  await page.getByRole('link', { name: '真实本地 BGE / Cross-Encoder 检索质量实验室' }).click()
  await expect(page.getByRole('heading', { name: '检索质量实验室', exact: true })).toBeVisible()
  await expect(page.getByRole('region', { name: '检索证据来源' })).toContainText('REAL_LOCAL_BGE')
  await expect(page.getByRole('region', { name: '检索证据来源' })).toContainText('SINGLE_ANNOTATOR')
  await expect(page.getByRole('region', { name: '四种检索对比' }).getByRole('row')).toHaveCount(5)
  await expect(page.getByRole('region', { name: '四种检索对比' })).toContainText('UNKNOWN')
  const root = process.env.AGENTMALL_RETRIEVAL_EVIDENCE_DIR ?? 'test-results/retrieval-quality'
  await mkdir(root, { recursive: true })
  await page.locator('main').click({ position: { x: 8, y: 8 } })
  await page.screenshot({ path: path.join(root, 'v210-overview.png'), fullPage: true })
  await page.getByLabel('检索品类', { exact: true }).selectOption('smartphone')
  await expect(page.getByLabel('检索失败案例').getByRole('listitem').first()).toBeVisible()
  await page.getByLabel('检索失败案例').getByRole('button').first().click()
  await expect(page.getByRole('region', { name: 'Top5差异' }).getByRole('article')).toHaveCount(4)
  await page.getByLabel('数据分区').selectOption('dev')
  await expect(page.getByRole('region', { name: '四种检索对比' })).toContainText('20 / 20')
  await page.setViewportSize({ width: 390, height: 844 })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await page.screenshot({ path: path.join(root, 'v210-mobile.png'), fullPage: true })
  expect(writes).toEqual([])
})

test('invalid or mismatched retrieval evidence fails closed without manufactured metrics', async ({ page }) => {
  await page.route('**/evals/retrieval-v1.json', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ schema_version: 99 }) }))
  await page.goto('/engineering/evals/retrieval')
  await expect(page.getByRole('alert')).toContainText('原件缺失或格式不一致')
  await expect(page.getByRole('table')).toHaveCount(0)
})
