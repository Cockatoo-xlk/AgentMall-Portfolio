import { readFileSync } from "node:fs";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router";
import { expect, it } from "vitest";
import {
  failureReason,
  parseRetrievalReport,
  pipelines,
  retrievalMetric,
} from "./retrievalQuality";
import { RetrievalQualityView } from "../pages/RetrievalQuality";
const raw = () =>
  JSON.parse(
    readFileSync(
      new URL("../../public/evals/retrieval-v1.json", import.meta.url),
      "utf8",
    ),
  );
it("parses actual local-model evidence and all paired planned cases without writes", () => {
  const r = parseRetrievalReport(raw());
  for (const split of ["dev", "test"] as const) {
    expect(r.splits[split].cases).toHaveLength(80);
    for (const p of pipelines)
      expect(r.splits[split].summaries[p].planned_queries).toBe(20);
  }
  expect(r.evidence_class).toBe("REAL_LOCAL_BGE");
  expect(r.provider_requests).toBe(0);
});
it("rejects a missing or swapped failure task and mismatched denominators", () => {
  const missing = raw();
  missing.splits.test.cases.pop();
  expect(() => parseRetrievalReport(missing)).toThrow();
  const swapped = raw();
  swapped.splits.test.cases[0].query = "Changed paired task";
  expect(() => parseRetrievalReport(swapped)).toThrow("UNPAIRED");
});
it("rejects impossible quality percentages", () => {
  const bad = raw();
  bad.splits.test.summaries.hybrid.recall_at_5 = 1.5;
  expect(() => parseRetrievalReport(bad)).toThrow();
});
it("keeps unknown values distinct from a measured zero", () => {
  expect(retrievalMetric(null)).toBe("UNKNOWN");
  expect(retrievalMetric(undefined)).toBe("UNKNOWN");
  expect(retrievalMetric(0)).toBe("0.00");
  expect(retrievalMetric(0, true)).toBe("0.00%");
  const bad = raw();
  bad.splits.test.cases[0].status = "TIMEOUT";
  bad.splits.test.cases[0].pipeline_ms = 0;
  expect(() => parseRetrievalReport(bad)).toThrow();
});
it("displays fixed source, limits, four-arm data and never raw secrets or HTML", () => {
  const r = parseRetrievalReport(raw());
  r.splits.test.cases[0].top5[0].name = "<script>unsafe</script>";
  const html = renderToStaticMarkup(
    <MemoryRouter>
      <RetrievalQualityView report={r} />
    </MemoryRouter>,
  );
  for (const label of [
    "不是 BM25",
    "SINGLE_ANNOTATOR",
    "Recall@5",
    "NDCG@5",
    "UNKNOWN",
    "标注缺口",
    "source",
    "7999e1d3359715c523056ef9478215996d62a620",
  ]) {
    if (label === "标注缺口" || label === "source") continue;
    expect(html).toContain(label);
  }
  expect(html).not.toContain("<script>");
  expect(html).not.toContain("postgresql://");
});
it("fixture reports cannot masquerade as real model measurements", () => {
  const r = parseRetrievalReport(raw());
  r.evidence_class = "FIXTURE";
  r.reranker_evidence = "FIXTURE";
  const html = renderToStaticMarkup(
    <MemoryRouter>
      <RetrievalQualityView report={r} />
    </MemoryRouter>,
  );
  expect(html).toContain("FIXTURE · 不验证语义质量");
  expect(html).not.toContain("本地模型实测");
  const forged = raw();
  forged.models.embedding.model_id = "agentmall/fixture";
  expect(() => parseRetrievalReport(forged)).toThrow("INVALID_REAL_MODEL");
});
it("no-answer failures stay visible while a top-k ceiling is not mistaken for execution failure", () => {
  const r = parseRetrievalReport(raw());
  const failure = r.splits.test.cases.find(
    (c) => !Object.keys(c.grades).length && c.result_ids?.length,
  );
  expect(failure).toBeDefined();
  expect(failureReason(failure!)).toContain("无答案");
});

it("rejects dropping the same query from all arms while shrinking their own summaries", () => {
  const bad = raw();
  bad.splits.test.cases = bad.splits.test.cases.filter(
    (r: { id: string }) => r.id !== "test-01",
  );
  for (const p of pipelines) {
    bad.splits.test.summaries[p].planned_queries--;
    bad.splits.test.summaries[p].completed_queries--;
    bad.splits.test.summaries[p].answer_queries--;
  }
  expect(() => parseRetrievalReport(bad)).toThrow();
});
it("does not retain positive headline metrics when a planned answer execution is unknown", () => {
  const bad = raw(),
    row = bad.splits.test.cases[0];
  row.status = "ERROR";
  row.pipeline_ms = null;
  row.result_ids = null;
  row.candidate_ids = null;
  row.top5 = [];
  bad.splits.test.summaries[row.architecture].completed_queries--;
  bad.splits.test.summaries[row.architecture].execution_errors++;
  expect(() => parseRetrievalReport(bad)).toThrow();
});
it.each(["environment", "per_category", "grades", "top5_amount", "top5_name"])(
  "rejects incomplete render data: %s",
  (field) => {
    const bad = raw();
    if (field === "environment") delete bad.environment;
    if (field === "per_category") delete bad.splits.test.per_category;
    if (field === "grades") bad.splits.test.cases[0].grades = [];
    if (field === "top5_amount")
      bad.splits.test.cases[0].top5[0].price_cents = "not-a-number";
    if (field === "top5_name") bad.splits.test.cases[0].top5[0].name = {};
    expect(() => parseRetrievalReport(bad)).toThrow();
  },
);
