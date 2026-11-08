import { test, expect } from "@playwright/test";
import type { APIRequestContext, Page } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import path from "node:path";
import { API_ORIGIN } from "./environment";
const api = API_ORIGIN + "/api/v1",
  password = "AgentMall-demo-2026!";
async function auth(request: APIRequestContext, login: string) {
  const r = await request.post(api + "/auth/login", {
    data: { login, password },
  });
  expect(r.ok()).toBeTruthy();
  return { Authorization: "Bearer " + (await r.json()).access_token };
}
async function post(
  request: APIRequestContext,
  headers: Record<string, string>,
  url: string,
  data: object,
) {
  const r = await request.post(api + url, {
    headers: { ...headers, "Idempotency-Key": crypto.randomUUID() },
    data,
  });
  expect(r.ok(), `${url}: ${r.status()}`).toBeTruthy();
  return r.json();
}
async function login(page: Page, user = "merchant") {
  await page.goto("/merchant");
  await page.getByRole("link", { name: "去登录" }).click();
  await page.getByLabel("账号", { exact: true }).fill(user);
  await page.getByLabel("密码", { exact: true }).fill(password);
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await expect(page.getByRole("button", { name: "退出登录" })).toBeVisible();
}
async function setup(request: APIRequestContext) {
  const buyer = await auth(request, "buyer1"),
    merchant = await auth(request, "merchant");
  const p = (await (await request.get(api + "/products")).json()).items[0];
  async function confirm(proposal: { proposal_id: string }) {
    return post(
      request,
      buyer,
      `/proposals/${proposal.proposal_id}/confirmations`,
      { decision: "approve" },
    );
  }
  async function paid() {
    const proposal = await post(request, buyer, "/checkout/proposals", {
      request_id: crypto.randomUUID(),
      address_label: "demo_dorm",
      items: [{ product_id: p.id, quantity: 1 }],
    });
    const receipt = await post(request, buyer, "/orders", {
      proposal_id: proposal.proposal_id,
      confirmation_id: (await confirm(proposal)).confirmation_id,
    });
    let order = await (
      await request.get(api + "/orders/" + receipt.order_id, { headers: buyer })
    ).json();
    const payment = await post(
      request,
      buyer,
      `/orders/${order.id}/payment-proposals`,
      { request_id: crypto.randomUUID(), expected_version: order.version },
    );
    await post(request, buyer, `/orders/${order.id}/mock-payments`, {
      proposal_id: payment.proposal_id,
      confirmation_id: (await confirm(payment)).confirmation_id,
    });
    order = await (
      await request.get(api + "/orders/" + order.id, { headers: buyer })
    ).json();
    return order;
  }
  const shipping = await paid();
  let delivered = await paid();
  for (const event of ["ship", "deliver"])
    delivered = await post(
      request,
      merchant,
      `/merchant/orders/${delivered.id}/${event}`,
      { expected_version: delivered.version },
    );
  const proposal = await post(request, buyer, "/after-sales/proposals", {
    request_id: crypto.randomUUID(),
    order_id: delivered.id,
    expected_version: delivered.version,
    reason_code: "QUALITY_ISSUE",
    description: "合成TEST_OPERATOR演示：商品质量问题",
  });
  const receipt = await post(request, buyer, "/after-sales", {
    proposal_id: proposal.proposal_id,
    confirmation_id: (await confirm(proposal)).confirmation_id,
  });
  const record = await (
    await request.get(api + "/merchant/after-sales/" + receipt.case_id, {
      headers: merchant,
    })
  ).json();
  return { merchant, buyer, shipping, record };
}
test.beforeEach(async ({ page, request }) => {
  await page.route("**/*", (route) =>
    new URL(route.request().url()).hostname === "127.0.0.1"
      ? route.continue()
      : route.abort(),
  );
  expect(
    (
      await request.post(API_ORIGIN + "/__test/reset", {
        headers: { "X-E2E-Key": "agentmall-local-e2e" },
        data: {},
      })
    ).ok(),
  ).toBeTruthy();
});
test("merchant copilot streams real tools before completion, cites actual records and only fills a review form", async ({
  page,
  request,
}) => {
  const fixture = await setup(request);
  const writes: string[] = [];
  page.on("request", (r) => {
    const u = new URL(r.url());
    if (
      u.pathname.startsWith("/api/v1/") &&
      !["GET", "HEAD"].includes(r.method()) &&
      !u.pathname.includes("/merchant/copilot/") &&
      !u.pathname.includes("/auth/login")
    )
      writes.push(u.pathname);
  });
  await login(page);
  await page.getByRole("button", { name: "AI运营助手", exact: true }).click();
  await expect(
    page.getByRole("region", { name: "AI运营助手", exact: true }),
  ).toContainText("MOCK_TRANSPORT");
  await page.getByRole("button", { name: "开始只读分析", exact: true }).click();
  await expect(
    page.getByRole("region", { name: "实际分析进度" }),
  ).toContainText("确定性汇总");
  await expect(page.getByRole("region", { name: "运营分析结果" })).toHaveCount(
    0,
  );
  await expect(
    page.getByRole("region", { name: "运营分析结果" }),
  ).toContainText(fixture.shipping.id);
  await expect(
    page.getByRole("region", { name: "运营分析结果" }),
  ).toContainText(fixture.record.id);
  await page.getByRole("button", { name: "为这笔售后草拟说明" }).click();
  await page.getByRole("button", { name: "开始只读分析", exact: true }).click();
  await expect(
    page.getByRole("region", { name: "审核说明草稿" }),
  ).toBeVisible();
  const output =
    process.env.AGENTMALL_COPILOT_EVIDENCE_DIR ??
    "test-results/merchant-copilot";
  await mkdir(output, { recursive: true });
  await page.screenshot({
    path: path.join(output, "review-evidence.png"),
    fullPage: true,
  });
  // Deterministically hold the real read-only check after its response is produced.
  let release!: () => void;
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route("**/merchant/copilot/check", async (route) => {
    const response = await route.fetch();
    await held;
    await route.fulfill({ response });
  });
  await page.getByRole("button", { name: "核对后仅填入审核表单" }).click();
  await expect(
    page.getByRole("button", { name: "开始只读分析", exact: true }),
  ).toBeDisabled();
  release();

  await expect(
    page.getByRole("textbox", { name: "审核说明", exact: true }),
  ).toHaveValue(/未经商家执行/);
  await expect(
    page.getByRole("button", { name: "审核通过", exact: true }),
  ).toBeEnabled();
  const unchanged = await (
    await request.get(api + "/merchant/after-sales/" + fixture.record.id, {
      headers: fixture.merchant,
    })
  ).json();
  expect(unchanged.status).toBe("REQUESTED");
  expect(unchanged.version).toBe(fixture.record.version);
  expect(writes).toEqual([]);
  await page.reload();
  await expect(page.getByRole("heading", { name: "登录后继续" })).toBeVisible();
  expect(
    (
      await (
        await request.get(api + "/merchant/after-sales/" + fixture.record.id, {
          headers: fixture.merchant,
        })
      ).json()
    ).status,
  ).toBe("REQUESTED");
});
test("partial inventory scope, mobile layout and account switching keep evidence bounded", async ({
  page,
  request,
}) => {
  expect(
    (
      await request.post(API_ORIGIN + "/__test/expanded-catalog", {
        headers: { "X-E2E-Key": "agentmall-local-e2e" },
        data: {},
      })
    ).ok(),
  ).toBeTruthy();
  await login(page);
  await page.getByRole("button", { name: "AI运营助手", exact: true }).click();
  await page.getByRole("button", { name: "库存与索引示例" }).click();
  await page.getByRole("button", { name: "开始只读分析", exact: true }).click();
  await expect(
    page.getByRole("region", { name: "运营分析结果" }),
  ).toContainText("已读取 40 条");
  await expect(
    page.getByRole("region", { name: "运营分析结果" }),
  ).toContainText("部分数据");
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  const output =
    process.env.AGENTMALL_COPILOT_EVIDENCE_DIR ??
    "test-results/merchant-copilot";
  await mkdir(output, { recursive: true });
  await page.screenshot({
    path: path.join(output, "inventory-mobile.png"),
    fullPage: true,
  });
  await page.getByRole("button", { name: "退出登录" }).click();
  await login(page, "buyer1");
  await expect(
    page.getByRole("heading", { name: "仅商家可访问" }),
  ).toBeVisible();
  await expect(page.getByRole("region", { name: "运营分析结果" })).toHaveCount(
    0,
  );
});
test("changed case blocks old draft and a broken stream does not automatically retry", async ({
  page,
  request,
}) => {
  const fixture = await setup(request);
  await login(page);
  await page.getByRole("button", { name: "售后管理", exact: true }).click();
  await page
    .getByRole("button", { name: `查看售后 ${fixture.record.id}`, exact: true })
    .click();
  await page.getByRole("button", { name: "让AI草拟审核说明" }).click();
  await page.getByRole("button", { name: "开始只读分析", exact: true }).click();
  await expect(
    page.getByRole("region", { name: "审核说明草稿" }),
  ).toBeVisible();
  await post(
    request,
    fixture.merchant,
    `/merchant/after-sales/${fixture.record.id}/review`,
    {
      expected_version: fixture.record.version,
      decision: "reject",
      reason: "TEST_OPERATOR独立操作，用于验证旧建议失效",
    },
  );
  await page.getByRole("button", { name: "核对后仅填入审核表单" }).click();
  await expect(page.getByRole("alert")).toContainText("数据已变化");
  let attempts = 0;
  await page.route("**/merchant/copilot/analyze/stream", (route) => {
    attempts++;
    return route.abort("failed");
  });
  await page.getByRole("button", { name: "开始只读分析", exact: true }).click();
  await expect(page.getByRole("alert")).toBeVisible();
  expect(attempts).toBe(1);
  expect(
    (
      await (
        await request.get(api + "/merchant/after-sales/" + fixture.record.id, {
          headers: fixture.merchant,
        })
      ).json()
    ).status,
  ).toBe("REJECTED");
});
