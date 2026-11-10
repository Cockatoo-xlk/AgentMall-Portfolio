import { expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { parseCopilotResult, coverageLabel } from "./merchantCopilot";
import { CopilotResultView } from "../components/MerchantCopilot";
const sample = () => ({
  status: "COMPLETED",
  clarification: null,
  model_mode: "MOCK_TRANSPORT",
  summary: {
    paid_orders: 0,
    requested_cases: null,
    out_of_stock: null,
    low_stock: null,
    index_pending: null,
    coverage: [
      {
        tool: "list_merchant_orders",
        status_filter: "PAID",
        scanned: 0,
        complete: true,
        next_cursor: null,
        started_cursor: null,
      },
    ],
    scope: "OBSERVED_RECORDS_ONLY",
    low_stock_threshold: 5,
    by_status: {},
    eligible_todo_count: 0,
    shown_todo_count: 0,
    advice_truncated: false,
  },
  evidence: [],
  suggestions: [],
  review_draft: null,
  metrics: {
    model_calls: 2,
    tool_calls: 2,
    db_pages: 1,
    verified_suggestions: 0,
    unsupported_claims: 0,
    business_writes: 0,
    permission_violations: 0,
    latency_ms: 2,
    grounded_claim_rate: null,
    input_token_upper_bound: 100,
    reported_fixture_input_tokens: 200,
    reported_fixture_output_tokens: 200,
  },
  limitations: ["Fixture, not real LLM"],
});
it("parses observed scope and keeps unread metrics distinct from measured zero", () => {
  const r = parseCopilotResult(sample());
  expect(r.summary.paid_orders).toBe(0);
  expect(r.summary.low_stock).toBeNull();
  expect(coverageLabel(r, "paid_orders")).toBe("0");
  const partial = sample();
  partial.summary.coverage[0].complete = false;
  expect(coverageLabel(parseCopilotResult(partial), "paid_orders")).toContain(
    "至少",
  );
});
it.each(["mode", "count", "scope", "evidence", "draft"])(
  "rejects invalid evidence: %s",
  (kind) => {
    const s = sample() as unknown as Record<string, unknown>;
    if (kind === "mode") s.model_mode = "LIVE";
    if (kind === "count")
      (s.summary as Record<string, unknown>).paid_orders = -1;
    if (kind === "scope")
      (s.summary as Record<string, unknown>).scope = "ALL_STORE";
    if (kind === "evidence")
      s.suggestions = [{ evidence_key: "order:unknown" }];
    if (kind === "draft")
      s.review_draft = { case_id: "unknown", text: "自动审核通过" };
    expect(() => parseCopilotResult(s)).toThrow();
  },
);
it("renders only advisory controls, UNKNOWN and explicit mock evidence", () => {
  const html = renderToStaticMarkup(
    <CopilotResultView
      result={parseCopilotResult(sample())}
      onOpen={() => {}}
    />,
  );
  expect(html).toContain("MOCK_TRANSPORT");
  expect(html).toContain("未读取");
  expect(html).toContain("未经商家执行");
  expect(html).not.toContain("执行退款");
  expect(html).not.toContain("Bearer");
});
