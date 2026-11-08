export const pipelines = [
  "lexical",
  "dense",
  "hybrid",
  "hybrid_reranker",
] as const;
export type Pipeline = (typeof pipelines)[number];
export const pipelineLabels: Record<Pipeline, string> = {
  lexical: "Lexical · ts_rank_cd",
  dense: "Dense · BGE",
  hybrid: "Hybrid · RRF",
  hybrid_reranker: "Hybrid + Cross-Encoder",
};
export interface RetrievalSummary {
  planned_queries: number;
  completed_queries: number;
  answer_queries: number;
  no_answer_queries: number;
  recall_at_5: number | null;
  mrr_at_5: number | null;
  ndcg_at_5: number | null;
  candidate_recall_at_20: number | null;
  candidate_ndcg_ceiling_at_5: number | null;
  no_answer_accuracy: number | null;
  latency_p50_ms: number | null;
  latency_p95_ms: number | null;
  rerank_mean_ms: number | null;
  model_calls_mean: number | null;
  illegal_result_count: number | null;
  stale_index_leak_count: number | null;
  execution_errors: number;
}
export interface RetrievalCase {
  id: string;
  query: string;
  category: string;
  architecture: Pipeline;
  status: string;
  error: string | null;
  grades: Record<string, number>;
  result_ids: string[] | null;
  candidate_ids: string[] | null;
  top5: {
    id: string;
    name: string;
    category: string;
    price_cents: number;
    catalog_version: number;
  }[];
  pipeline_ms: number | null;
  rerank_ms: number | null;
  annotation_basis: string;
  violations: string[];
  metrics: {
    recall_at_5: number | null;
    mrr_at_5: number | null;
    ndcg_at_5: number | null;
  };
}
export interface RetrievalReport {
  schema_version: number;
  evidence_class: "REAL_LOCAL_BGE" | "FIXTURE";
  reranker_evidence: string;
  evaluation_run_id: string;
  executed_at: string;
  recommendation: string;
  known_label_issues: string[];
  source: {
    git_base_sha: string;
    worktree_dirty: boolean;
    source_tree_sha256: string;
    binding: string;
  };
  dataset: {
    dataset_version: string;
    annotation: string;
    splits: Record<string, string>;
    planned_queries: Record<"dev" | "test", number>;
    protocol: {
      final_k: number;
      candidate_count: number;
      min_similarity: number;
      dcg: string;
    };
  };
  environment: {
    platform: string;
    architecture: string;
    python: string;
    device: string;
  };
  models: {
    embedding: {
      model_id: string;
      revision: string;
      dimension: number;
      cold_load_ms: number;
    };
    reranker: {
      model_id: string;
      revision: string;
      cold_load_ms: number;
      max_tokens: number;
      batch_size: number;
    };
  };
  splits: Record<
    "dev" | "test",
    {
      cases: RetrievalCase[];
      summaries: Record<Pipeline, RetrievalSummary>;
      per_category: Record<Pipeline, Record<string, RetrievalSummary>>;
    }
  >;
  provider_requests: number;
  limitations: string[];
}
function obj(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value))
    throw Error("INVALID_RETRIEVAL_REPORT");
  return value as Record<string, unknown>;
}
const metricKeys = [
  "recall_at_5",
  "mrr_at_5",
  "ndcg_at_5",
  "candidate_recall_at_20",
  "candidate_ndcg_ceiling_at_5",
  "no_answer_accuracy",
  "latency_p50_ms",
  "latency_p95_ms",
  "rerank_mean_ms",
  "model_calls_mean",
  "illegal_result_count",
  "stale_index_leak_count",
];
const frozenSplits = {
  dev: "b697e42451b7ba7dce51b2ebd56396b1388d2534930d3bc180d7b31df4783694",
  test: "611c5eb6c354f0fc9dd80e739f62e33d7ce033060dae709b7a5f44e215218422",
};
function textValue(value: unknown): asserts value is string {
  if (typeof value !== "string" || !value.length)
    throw Error("INVALID_REPORT_TEXT");
}
function strings(value: unknown): asserts value is string[] {
  if (!Array.isArray(value) || value.some((v) => typeof v !== "string"))
    throw Error("INVALID_REPORT_TEXT_ARRAY");
}
function count(value: unknown): asserts value is number {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < 0)
    throw Error("INVALID_REPORT_COUNT");
}
function numeric(value: unknown, fraction = false) {
  if (
    value !== null &&
    (typeof value !== "number" ||
      !Number.isFinite(value) ||
      value < 0 ||
      (fraction && value > 1))
  )
    throw Error("INVALID_RETRIEVAL_METRIC");
}
function validateRow(row: Record<string, unknown>) {
  for (const k of ["id", "query", "category", "status", "annotation_basis"])
    textValue(row[k]);
  const grades = obj(row.grades);
  for (const [id, grade] of Object.entries(grades)) {
    if (
      !/^[a-f0-9-]{36}$/.test(id) ||
      ![1, 2, 3].includes(Number(grade)) ||
      typeof grade !== "number"
    )
      throw Error("INVALID_JUDGMENT");
  }
  obj(row.filters);
  strings(row.violations);
  if (!Array.isArray(row.top5) || row.top5.length > 5)
    throw Error("INVALID_RETRIEVAL_CASE");
  numeric(row.pipeline_ms);
  numeric(row.rerank_ms);
  for (const k of metricKeys.slice(0, 5)) numeric(obj(row.metrics)[k], true);
  if (row.status !== "OK") {
    if (
      row.pipeline_ms !== null ||
      row.result_ids !== null ||
      row.candidate_ids !== null ||
      row.top5.length ||
      metricKeys.slice(0, 5).some((k) => obj(row.metrics)[k] !== null)
    )
      throw Error("MISSING_IS_NOT_ZERO");
    return;
  }
  strings(row.result_ids);
  strings(row.candidate_ids);
  if (
    row.result_ids.length > 5 ||
    row.candidate_ids.length > 20 ||
    new Set(row.result_ids).size !== row.result_ids.length ||
    new Set(row.candidate_ids).size !== row.candidate_ids.length ||
    row.result_ids.some(
      (id) => !(row.candidate_ids as string[]).includes(id),
    ) ||
    row.top5.length !== row.result_ids.length ||
    row.pipeline_ms === null
  )
    throw Error("INVALID_RETRIEVAL_CASE");
  for (const [i, item] of row.top5.entries()) {
    const hit = obj(item);
    if (hit.id !== row.result_ids[i]) throw Error("INVALID_RESULT_BINDING");
    textValue(hit.id);
    textValue(hit.name);
    textValue(hit.category);
    count(hit.price_cents);
    count(hit.catalog_version);
    if (hit.catalog_version === 0) throw Error("INVALID_RESULT_VERSION");
  }
  const hasAnswer = Object.keys(grades).length > 0;
  if (
    metricKeys
      .slice(0, 5)
      .some((k) => (obj(row.metrics)[k] === null) === hasAnswer)
  )
    throw Error("INVALID_CASE_METRIC_AVAILABILITY");
}
function validateSummary(value: unknown, rows: Record<string, unknown>[]) {
  const summary = obj(value);
  for (const k of [
    "planned_queries",
    "completed_queries",
    "answer_queries",
    "no_answer_queries",
    "execution_errors",
  ])
    count(summary[k]);
  const answers = rows.filter((r) => Object.keys(obj(r.grades)).length > 0);
  const empty = rows.filter((r) => !Object.keys(obj(r.grades)).length);
  const completed = rows.filter((r) => r.status === "OK").length;
  if (
    summary.planned_queries !== rows.length ||
    summary.completed_queries !== completed ||
    summary.execution_errors !== rows.length - completed ||
    summary.answer_queries !== answers.length ||
    summary.no_answer_queries !== empty.length
  )
    throw Error("INVALID_RETRIEVAL_DENOMINATOR");
  for (const [i, k] of metricKeys.entries()) numeric(summary[k], i < 6);
  const answerUnknown =
    !answers.length || answers.some((r) => r.status !== "OK");
  const noAnswerUnknown = !empty.length || empty.some((r) => r.status !== "OK");
  if (
    metricKeys
      .slice(0, 5)
      .some((k) => (summary[k] === null) !== answerUnknown) ||
    (summary.no_answer_accuracy === null) !== noAnswerUnknown
  )
    throw Error("MISSING_IS_NOT_ZERO");
  if (
    completed !== rows.length &&
    [
      "latency_p50_ms",
      "latency_p95_ms",
      "model_calls_mean",
      "illegal_result_count",
      "stale_index_leak_count",
    ].some((k) => summary[k] !== null)
  )
    throw Error("MISSING_IS_NOT_ZERO");
}
export function parseRetrievalReport(value: unknown): RetrievalReport {
  const root = obj(value),
    data = obj(root.dataset),
    source = obj(root.source),
    models = obj(root.models);
  if (
    root.schema_version !== 1 ||
    !["REAL_LOCAL_BGE", "FIXTURE"].includes(String(root.evidence_class))
  )
    throw Error("INVALID_RETRIEVAL_REPORT");
  for (const k of [
    "evaluation_run_id",
    "executed_at",
    "recommendation",
    "reranker_evidence",
  ])
    textValue(root[k]);
  strings(root.known_label_issues);
  strings(root.limitations);
  count(root.provider_requests);
  if (
    !/^[a-f0-9]{40}$/.test(String(source.git_base_sha)) ||
    !/^[a-f0-9]{64}$/.test(String(source.source_tree_sha256)) ||
    typeof source.worktree_dirty !== "boolean"
  )
    throw Error("INVALID_SOURCE_IDENTITY");
  textValue(source.binding);
  const environment = obj(root.environment);
  for (const k of ["platform", "architecture", "python", "device"])
    textValue(environment[k]);
  for (const k of ["dataset_version", "annotation"]) textValue(data[k]);
  if (data.dataset_version !== "expanded-retrieval-v1")
    throw Error("UNKNOWN_DATASET_VERSION");
  const protocol = obj(data.protocol);
  if (
    protocol.final_k !== 5 ||
    protocol.candidate_count !== 20 ||
    protocol.min_similarity !== 0.45
  )
    throw Error("INCOMPARABLE_RETRIEVAL_PROTOCOL");
  textValue(protocol.dcg);
  const embedding = obj(models.embedding),
    reranker = obj(models.reranker);
  for (const model of [embedding, reranker]) {
    textValue(model.model_id);
    textValue(model.revision);
    numeric(model.cold_load_ms);
  }
  count(embedding.dimension);
  count(reranker.max_tokens);
  count(reranker.batch_size);
  if (
    root.evidence_class === "REAL_LOCAL_BGE" &&
    (embedding.model_id !== "BAAI/bge-small-zh-v1.5" ||
      embedding.revision !== "7999e1d3359715c523056ef9478215996d62a620" ||
      embedding.dimension !== 512 ||
      reranker.model_id !== "BAAI/bge-reranker-base" ||
      reranker.revision !== "2cfc18c9415c912f9d8155881c133215df768a70" ||
      root.reranker_evidence !== "REAL_LOCAL_CROSS_ENCODER")
  )
    throw Error("INVALID_REAL_MODEL_EVIDENCE");
  for (const split of ["dev", "test"] as const) {
    const part = obj(obj(root.splits)[split]);
    // This version is bound to the frozen JSONL roster, not to self-reported summaries.
    if (
      !Array.isArray(part.cases) ||
      obj(data.splits)[split] !== frozenSplits[split] ||
      obj(data.planned_queries)[split] !== 20 ||
      part.cases.length !== 80
    )
      throw Error("INVALID_DATASET_BINDING");
    const allRows = part.cases.map(obj);
    if (allRows.some((r) => !pipelines.includes(r.architecture as Pipeline)))
      throw Error("UNKNOWN_PIPELINE");
    const roster = Array.from(
      { length: 20 },
      (_, i) => `${split}-${String(i + 1).padStart(2, "0")}`,
    );
    let reference = "";
    for (const arm of pipelines) {
      const rows = allRows.filter((r) => r.architecture === arm);
      for (const row of rows) validateRow(row);
      if (
        JSON.stringify(rows.map((r) => r.id).sort()) !== JSON.stringify(roster)
      )
        throw Error("INVALID_RETRIEVAL_DENOMINATOR");
      validateSummary(obj(part.summaries)[arm], rows);
      const signature = JSON.stringify(
        rows
          .map((r) => [r.id, r.query, r.grades, r.filters])
          .sort((a, b) => String(a[0]).localeCompare(String(b[0]))),
      );
      if (reference && reference !== signature)
        throw Error("UNPAIRED_RETRIEVAL_CASES");
      reference = signature;
      const categories = obj(obj(part.per_category)[arm]);
      const expected = [...new Set(rows.map((r) => String(r.category)))].sort();
      if (
        JSON.stringify(Object.keys(categories).sort()) !==
        JSON.stringify(expected)
      )
        throw Error("INVALID_CATEGORY_DENOMINATOR");
      for (const category of expected)
        validateSummary(
          categories[category],
          rows.filter((r) => r.category === category),
        );
    }
  }
  return value as RetrievalReport;
}
export function retrievalMetric(
  value: number | null | undefined,
  percent = false,
) {
  return typeof value === "number" && Number.isFinite(value)
    ? percent
      ? `${(value * 100).toFixed(2)}%`
      : value.toFixed(2)
    : "UNKNOWN";
}
export function failureReason(row: RetrievalCase): string {
  if (row.status !== "OK") return row.error ?? row.status;
  if (row.violations.length) return "非法或过期结果";
  const n = Object.keys(row.grades).length;
  if (!n) return row.result_ids?.length ? "无答案查询误返商品" : "";
  const ceiling = Math.min(5, n) / n;
  if (
    row.metrics.recall_at_5 !== null &&
    row.metrics.recall_at_5 + 1e-9 < ceiling
  )
    return "相关商品未进入 Top 5；请同时检查候选召回上限";
  if (row.metrics.ndcg_at_5 !== null && row.metrics.ndcg_at_5 < 0.99999)
    return "分级相关性排序不理想";
  return "";
}
