import { expect, test } from '@playwright/test'
import type { APIRequestContext } from '@playwright/test'
import { mkdir } from 'node:fs/promises'
import path from 'node:path'
import { API_ORIGIN } from './environment'

async function control(request: APIRequestContext, route: string, data?: object) {
  const headers = { 'X-E2E-Key': 'agentmall-local-e2e' }
  const response = data === undefined ? await request.get(`${API_ORIGIN}/__test${route}`, { headers }) : await request.post(`${API_ORIGIN}/__test${route}`, { headers, data })
  expect(response.ok()).toBe(true)
  return response.json()
}

test('expanded catalogue: thirteen categories, 120 unique products, mobile filters, cart and independent checkout', async ({ page, request }) => {
  await control(request, '/reset', {})
  await control(request, '/expanded-catalog', {})
  await page.route('**/*', route => new URL(route.request().url()).hostname === '127.0.0.1' ? route.continue() : route.abort())
  await page.goto('/')
  await expect(page.getByRole('button', { name: '手机', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '骑行装备', exact: true })).toBeVisible()
  const screenshots = process.env.AGENTMALL_CATALOG_SCREENSHOTS
  await expect(page.getByTestId('product-card')).toHaveCount(8)
  if (screenshots) {
    await mkdir(screenshots, { recursive: true })
    await page.screenshot({ path: path.join(screenshots, '01-expanded-desktop.png'), fullPage: true })
  }
  const ids = new Set<string>()
  while (true) {
    await expect(page.getByTestId('product-card').first()).toBeVisible()
    for (const href of await page.getByTestId('product-card').locator('h3 a').evaluateAll(links => links.map(a => a.getAttribute('href')!))) ids.add(href)
    const more = page.getByRole('button', { name: '加载更多', exact: true })
    if (!await more.count()) break
    const count = await page.getByTestId('product-card').count()
    await more.click()
    await expect(page.getByTestId('product-card')).not.toHaveCount(count)
  }
  expect(ids.size).toBe(120)
  await expect(page.getByTestId('product-card')).toHaveCount(120)
  await page.getByRole('button', { name: '手机', exact: true }).click()
  await page.getByLabel('最高预算（元）').fill('3000')
  await page.getByRole('button', { name: '筛选商品', exact: true }).click()
  await expect(page.getByTestId('product-card')).toHaveCount(6)
  await expect(page.getByTestId('product-card').first()).toContainText('GB')
  await page.getByTestId('product-card').first().locator('h3 a').click()
  await expect(page.getByRole('heading', { name: '商品参数' })).toBeVisible()
  await expect(page.getByText('内存', { exact: true })).toBeVisible()
  await page.getByRole('link', { name: '登录后加入购物车', exact: true }).click()
  await page.getByLabel('账号', { exact: true }).fill('buyer1')
  await page.getByLabel('密码', { exact: true }).fill('AgentMall-demo-2026!')
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await expect(page.getByRole('button', { name: '退出登录' })).toBeVisible()
  await page.getByRole('button', { name: '手机', exact: true }).click()
  const card = page.getByTestId('product-card').first()
  await card.getByRole('button', { name: '加入购物车', exact: true }).click()
  await expect(card).toContainText('购物车 1 件')
  await page.getByRole('link', { name: /购物车/ }).first().click()
  await page.getByRole('button', { name: '生成购买提案' }).click()
  await expect(page.getByRole('heading', { name: /确认/ }).first()).toBeVisible()
  expect((await control(request, '/facts')).orders).toBe(0)
  if (screenshots) await page.screenshot({ path: path.join(screenshots, '02-phone-confirmation.png'), fullPage: true })
  // Synthetic TEST_OPERATOR confirmation; never a real buyer authorization.
  await page.getByRole('button', { name: '确认并创建订单', exact: true }).click()
  await expect(page.getByText('订单已创建', { exact: true })).toBeVisible()
  const facts = await control(request, '/facts')
  expect(facts.orders).toBe(1)
  expect(facts.order_rows[0].status).toBe('PENDING_PAYMENT')
  expect(facts.payment_rows).toHaveLength(0)
  await page.reload()
  expect((await control(request, '/facts')).orders).toBe(1)
  expect(facts.real_model_calls).toBe(0)
  expect(facts.provider_http_requests).toBe(0)
  await page.goto('/')
  await page.setViewportSize({ width: 390, height: 844 })
  await page.getByRole('button', { name: '骑行装备', exact: true }).click()
  await expect(page.getByTestId('product-card').first()).toContainText('骑行')
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390)
  if (screenshots) await page.screenshot({ path: path.join(screenshots, '03-cycling-mobile.png'), fullPage: true })
})
