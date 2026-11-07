import { test, expect } from "@playwright/test";
import type { Page } from "@playwright/test";
import { API_ORIGIN } from "./environment";
import { mkdir } from "node:fs/promises";
import path from "node:path";
const controls = { "X-E2E-Key": "agentmall-local-e2e" };
const data = {
  name: "合成晨阅 N27 显示器",
  category: null,
  description:
    "27英寸、2560×1440、165Hz、IPS面板、支持HDMI和DisplayPort的办公显示器。",
  price_cents: 89900,
  on_hand: 12,
  attributes: {},
};
async function login(page: Page, user = "merchant") {
  await page.goto("/login");
  await page.getByLabel("账号", { exact: true }).fill(user);
  await page.getByLabel("密码", { exact: true }).fill("AgentMall-demo-2026!");
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await expect(page.getByRole("button", { name: "退出登录" })).toBeVisible();
}
async function workbench(page: Page) {
  await page.locator('a[href="/merchant"]').first().click();
  await page.getByRole("button", { name: "商品管理", exact: true }).click();
  await expect(page.getByText("MOCK_TRANSPORT", { exact: true })).toBeVisible();
}
test.beforeEach(async ({ page, request }) => {
  expect(
    (
      await request.post(API_ORIGIN + "/__test/reset", {
        headers: controls,
        data: {},
      })
    ).ok(),
  ).toBeTruthy();
  expect(
    (
      await request.post(API_ORIGIN + "/__test/sdk-mode", {
        headers: controls,
        data: { program: "bundle" },
      })
    ).ok(),
  ).toBeTruthy();
  await page.route("**/*", (route) =>
    new URL(route.request().url()).hostname === "127.0.0.1"
      ? route.continue()
      : route.abort(),
  );
});
test("merchant import, separate review/publication/index and buyer checkout preserve snapshots", async ({
  page,
  request,
}) => {
  await login(page);
  await workbench(page);
  await page.getByText("批量导入CSV / JSON", { exact: false }).click();
  await page.getByLabel("商品资料文件").setInputFiles({
    name: "synthetic.json",
    mimeType: "application/json",
    buffer: Buffer.from(JSON.stringify([data])),
  });
  await page.getByRole("button", { name: "导入为草稿", exact: true }).click();
  await page.getByRole("button", { name: "打开第1个草稿" }).click();
  const detail = page.getByRole("region", { name: "商品草稿详情" });
  await expect(detail).toContainText("SUGGESTED");
  await expect(detail.getByRole("heading")).toContainText("DRAFT");
  await detail.getByText("原始输入与规格依据", { exact: true }).click();
  await expect(detail).toContainText("panel = IPS");
  const screenshotRoot = process.env.AGENTMALL_OPERATIONS_SCREENSHOTS;
  if (screenshotRoot) {
    await mkdir(screenshotRoot, { recursive: true });
    await detail.screenshot({
      path: path.join(screenshotRoot, "01-source-backed-draft.png"),
    });
  }
  await page.getByRole("button", { name: "提交审核", exact: true }).click();
  await expect(detail.getByRole("heading")).toContainText("READY_FOR_REVIEW");
  await expect(detail.getByLabel("单价（分）", { exact: true })).toBeDisabled();
  await expect(
    page.getByRole("button", { name: "审核通过（不自动上架）" }),
  ).toBeDisabled();
  await page.getByLabel("我已核对原始资料", { exact: false }).check();
  await page.getByRole("button", { name: "审核通过（不自动上架）" }).click();
  await expect(detail.getByRole("heading")).toContainText("APPROVED");
  await expect(detail.getByLabel("单价（分）", { exact: true })).toBeDisabled();
  let products = await (
    await request.get(API_ORIGIN + "/api/v1/products?category=monitor")
  ).json();
  expect(
    products.items.some((p: { name: string }) => p.name === data.name),
  ).toBe(false);
  await page.getByRole("button", { name: "正式发布商品", exact: true }).click();
  await expect(detail.getByRole("heading")).toContainText("PUBLISHED");
  await page.getByRole("button", { name: "索引任务", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "索引 PENDING" }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "执行 / 重试索引", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "索引 SUCCEEDED" }),
  ).toBeVisible();
  if (screenshotRoot)
    await page.screenshot({
      path: path.join(screenshotRoot, "02-published-indexed.png"),
      fullPage: true,
    });
  await page.getByRole("button", { name: "退出登录" }).click();
  await login(page, "buyer1");
  await page.getByRole("link", { name: "AgentMall 首页", exact: true }).click();
  await page.getByRole("button", { name: "显示器", exact: true }).click();
  const card = page.getByTestId("product-card").filter({ hasText: data.name });
  await expect(card).toBeVisible();
  if (screenshotRoot)
    await card.screenshot({
      path: path.join(screenshotRoot, "03-buyer-new-product.png"),
    });
  await card.getByRole("button", { name: "加入购物车", exact: true }).click();
  await page
    .getByRole("link", { name: /购物车/ })
    .first()
    .click();
  await page.getByRole("button", { name: "生成购买提案", exact: true }).click();
  const before = await (
    await request.get(API_ORIGIN + "/__test/facts", { headers: controls })
  ).json();
  expect(before.orders).toBe(0);
  expect(before.confirmations).toBe(0);
  // Synthetic TEST_OPERATOR, never a real merchant/user authorization.
  await page
    .getByRole("button", { name: "确认并创建订单", exact: true })
    .click();
  await expect(page.getByRole("heading", { name: "订单详情" })).toBeVisible();
  const facts = await (
    await request.get(API_ORIGIN + "/__test/facts", { headers: controls })
  ).json();
  expect(facts.order_rows).toHaveLength(1);
  expect(facts.order_rows[0].status).toBe("PENDING_PAYMENT");
  expect(facts.order_rows[0].total_cents).toBe(89900);
  expect(facts.payment_rows).toHaveLength(0);
  const product = facts.product_rows.find(
    (p: { name: string }) => p.name === data.name,
  );
  expect(product.reserved).toBe(1);
  await page.reload();
  expect(
    (
      await (
        await request.get(API_ORIGIN + "/__test/facts", { headers: controls })
      ).json()
    ).orders,
  ).toBe(1);
  products = await (
    await request.get(API_ORIGIN + "/api/v1/products?category=monitor")
  ).json();
  expect(
    products.items.find((p: { id: string }) => p.id === product.id).available,
  ).toBe(11);
});
test("buyer cannot use merchant catalog and refresh never writes", async ({
  page,
  request,
}) => {
  await page.goto("/merchant");
  await page.getByRole("link", { name: "去登录", exact: true }).click();
  await page.getByLabel("账号", { exact: true }).fill("buyer1");
  await page.getByLabel("密码", { exact: true }).fill("AgentMall-demo-2026!");
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "仅商家可访问" }),
  ).toBeVisible();
  expect(
    await page.getByRole("button", { name: "商品管理", exact: true }).count(),
  ).toBe(0);
  let writes = 0;
  page.on("request", (r) => {
    if (r.url().includes("/merchant/catalog") && r.method() !== "GET") writes++;
  });
  await page.reload();
  expect(writes).toBe(0);
  expect(
    (
      await (
        await request.get(API_ORIGIN + "/__test/facts", { headers: controls })
      ).json()
    ).orders,
  ).toBe(0);
});
test("lost import response recovers same command receipt without duplicate drafts", async ({
  page,
}) => {
  await login(page);
  await workbench(page);
  await page.getByText("批量导入CSV / JSON", { exact: false }).click();
  await page.getByLabel("商品资料文本").fill(JSON.stringify([data]));
  await page.route("**/api/v1/merchant/catalog/imports", async (route) => {
    if (route.request().method() === "POST") {
      await route.fetch();
      await route.abort("connectionreset");
    } else await route.continue();
  });
  await page.getByRole("button", { name: "导入为草稿", exact: true }).click();
  await expect(page.getByText("请求结果未知", { exact: false })).toBeVisible();
  await page.getByRole("button", { name: "只读核对回执", exact: true }).click();
  await expect(page.getByRole("button", { name: "打开第1个草稿" })).toHaveCount(
    1,
  );
  await page.getByRole("button", { name: "商品草稿", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "查看 / 审核草稿", exact: true }),
  ).toHaveCount(1);
});

test("review snapshot stays read-only until an explicit return to editing revokes approval", async ({
  page,
  request,
}) => {
  await login(page);
  await workbench(page);
  await page.getByRole("button", { name: "创建商品草稿", exact: true }).click();
  await page.getByLabel("商品名称", { exact: true }).fill("合成审核显示器");
  await page.getByRole("combobox", { name: "商品品类", exact: true }).selectOption("monitor");
  await page.getByLabel("单价（分）", { exact: true }).fill("50000");
  await page.getByLabel("总库存", { exact: true }).fill("5");
  await page.getByRole("button", { name: "保存草稿", exact: true }).click();
  const detail = page.getByRole("region", { name: "商品草稿详情" });
  await expect(detail.getByRole("heading")).toContainText("DRAFT");
  await page.getByRole("button", { name: "提交审核", exact: true }).click();
  await expect(detail.getByLabel("单价（分）", { exact: true })).toBeDisabled();
  await page.getByLabel("我已核对原始资料", { exact: false }).check();
  await page
    .getByRole("button", { name: "审核通过（不自动上架）", exact: true })
    .click();
  await expect(detail.getByRole("heading")).toContainText("APPROVED");
  await expect(detail.getByLabel("单价（分）", { exact: true })).toBeDisabled();
  await page
    .getByRole("button", { name: "返回编辑（撤销审核）", exact: true })
    .click();
  await expect(detail.getByRole("heading")).toContainText("DRAFT");
  await expect(detail.getByLabel("单价（分）", { exact: true })).toBeEnabled();
  await detail.getByLabel("单价（分）", { exact: true }).fill("55000");
  await page.getByRole("button", { name: "保存草稿", exact: true }).click();
  await expect(detail.getByRole("heading")).toContainText("v5");
  await expect(
    page.getByRole("button", { name: "正式发布商品", exact: true }),
  ).toHaveCount(0);
  const facts = await (
    await request.get(API_ORIGIN + "/__test/facts", { headers: controls })
  ).json();
  expect(
    facts.product_rows.some(
      (p: { name: string }) => p.name === "合成审核显示器",
    ),
  ).toBe(false);
  expect(facts.orders).toBe(0);
});
