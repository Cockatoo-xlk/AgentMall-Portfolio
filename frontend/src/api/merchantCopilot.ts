export interface CopilotEvidence {
  key: string;
  kind: "order" | "case" | "product" | "index_job" | "policy";
  id: string;
  status: string;
  version: number | string;
  read_at: string;
  fingerprint: string;
  facts: Record<string, unknown>;
}
export interface ReviewSuggestion {
  case_id: string;
  case_version: number;
  policy_version: string;
  evidence_keys: string[];
  text: string;
}
export interface CopilotResult {
  status: "COMPLETED" | "NEEDS_INPUT";
  clarification: string | null;
  model_mode: "MOCK_TRANSPORT";
  summary: {
    paid_orders: number | null;
    requested_cases: number | null;
    out_of_stock: number | null;
    low_stock: number | null;
    index_pending: number | null;
    coverage: {
      tool: string;
      status_filter: string | null;
      scanned: number;
      complete: boolean;
      next_cursor: string | null;
      started_cursor: string | null;
    }[];
    scope: "OBSERVED_RECORDS_ONLY";
    low_stock_threshold: number;
    by_status: Record<string, Record<string, number>>;
    eligible_todo_count: number;
    shown_todo_count: number;
    advice_truncated: boolean;
  };
  evidence: CopilotEvidence[];
  suggestions: {
    type: string;
    content: string;
    evidence_key: string;
    record_id: string;
    status: string;
    version: string | number;
    read_at: string;
    action: string;
    risk: string;
    priority_rule: string;
  }[];
  review_draft: ReviewSuggestion | null;
  metrics: {
    model_calls: number;
    tool_calls: number;
    db_pages: number;
    verified_suggestions: number;
    unsupported_claims: number;
    business_writes: number;
    permission_violations: number;
    latency_ms: number;
    grounded_claim_rate: number | null;
    input_token_upper_bound: number;
    reported_fixture_input_tokens: number;
    reported_fixture_output_tokens: number;
  };
  limitations: string[];
}
export const metricTools = {
  paid_orders: "list_merchant_orders",
  requested_cases: "list_merchant_after_sales",
  out_of_stock: "list_merchant_products",
  low_stock: "list_merchant_products",
  index_pending: "list_catalog_index_jobs",
} as const;
export type CopilotMetric = keyof typeof metricTools;
function obj(v: unknown): Record<string, unknown> {
  if (!v || typeof v !== "object" || Array.isArray(v))
    throw Error("COPILOT_INVALID_EVIDENCE");
  return v as Record<string, unknown>;
}
function text(v: unknown) {
  if (typeof v !== "string" || !v.length) throw Error("COPILOT_INVALID_TEXT");
}
function count(v: unknown) {
  if (typeof v !== "number" || !Number.isSafeInteger(v) || v < 0)
    throw Error("COPILOT_INVALID_COUNT");
}
export function parseCopilotResult(value: unknown): CopilotResult {
  const v = obj(value),
    s = obj(v.summary),
    m = obj(v.metrics);
  if (
    !["COMPLETED", "NEEDS_INPUT"].includes(String(v.status)) ||
    v.model_mode !== "MOCK_TRANSPORT" ||
    s.scope !== "OBSERVED_RECORDS_ONLY"
  )
    throw Error("COPILOT_INVALID_SOURCE");
  if (
    !Array.isArray(s.coverage) ||
    s.coverage.length > 6 ||
    !Array.isArray(v.evidence) ||
    v.evidence.length > 200 ||
    !Array.isArray(v.suggestions) ||
    v.suggestions.length > 20 ||
    !Array.isArray(v.limitations) ||
    v.limitations.some((x) => typeof x !== "string")
  )
    throw Error("COPILOT_INVALID_SHAPE");
  for (const scope of s.coverage) {
    const c = obj(scope);
    text(c.tool);
    count(c.scanned);
    if (typeof c.complete !== "boolean")
      throw Error("COPILOT_INVALID_COVERAGE");
  }
  for (const [k, tool] of Object.entries(metricTools)) {
    if (s[k] !== null) count(s[k]);
    if ((s[k] === null) === s.coverage.some((c) => obj(c).tool === tool))
      throw Error("COPILOT_INVALID_DENOMINATOR");
  }
  for (const k of [
    "low_stock_threshold",
    "eligible_todo_count",
    "shown_todo_count",
  ])
    count(s[k]);
  if (
    typeof s.advice_truncated !== "boolean" ||
    s.shown_todo_count !== v.suggestions.length
  )
    throw Error("COPILOT_INVALID_COUNT");
  const ids = new Map<string, Record<string, unknown>>();
  for (const raw of v.evidence) {
    const e = obj(raw);
    for (const k of ["key", "id", "kind", "status", "read_at", "fingerprint"])
      text(e[k]);
    if (
      !["order", "case", "product", "index_job", "policy"].includes(
        String(e.kind),
      ) ||
      e.key !== `${e.kind}:${e.id}` ||
      !/^[a-f0-9-]{36}$/.test(String(e.id)) ||
      !/^[a-f0-9]{64}$/.test(String(e.fingerprint)) ||
      ids.has(String(e.key))
    )
      throw Error("COPILOT_INVALID_REFERENCE");
    if (e.kind === "policy") text(e.version);
    else {
      count(e.version);
      if (e.version === 0) throw Error("COPILOT_INVALID_VERSION");
    }
    obj(e.facts);
    ids.set(String(e.key), e);
  }
  for (const raw of v.suggestions) {
    const a = obj(raw),
      e = ids.get(String(a.evidence_key));
    if (
      !e ||
      !["SHIP", "REVIEW", "RESTOCK", "CHECK_INDEX"].includes(String(a.type)) ||
      a.record_id !== e.id ||
      a.status !== e.status ||
      a.version !== e.version
    )
      throw Error("COPILOT_UNSUPPORTED_REFERENCE");
    for (const k of ["content", "action", "risk", "read_at", "priority_rule"])
      text(a[k]);
  }
  if (v.review_draft !== null) {
    const d = obj(v.review_draft),
      e = ids.get(`case:${d.case_id}`);
    text(d.text);
    text(d.policy_version);
    count(d.case_version);
    if (
      !e ||
      e.status !== "REQUESTED" ||
      d.case_version !== e.version ||
      !Array.isArray(d.evidence_keys) ||
      !d.evidence_keys.every((k) => ids.has(String(k))) ||
      !d.evidence_keys.some((k) => ids.get(String(k))?.kind === "policy")
    )
      throw Error("COPILOT_INVALID_DRAFT");
  }
  for (const k of [
    "model_calls",
    "tool_calls",
    "db_pages",
    "verified_suggestions",
    "unsupported_claims",
    "business_writes",
    "permission_violations",
    "input_token_upper_bound",
    "reported_fixture_input_tokens",
    "reported_fixture_output_tokens",
  ])
    count(m[k]);
  if (
    m.business_writes !== 0 ||
    m.permission_violations !== 0 ||
    m.unsupported_claims !== 0 ||
    Number(m.model_calls) > 2 ||
    Number(m.tool_calls) > 7 ||
    typeof m.latency_ms !== "number" ||
    !Number.isFinite(m.latency_ms) ||
    m.latency_ms < 0
  )
    throw Error("COPILOT_SAFETY_VIOLATION");
  if (m.grounded_claim_rate !== null && m.grounded_claim_rate !== 1)
    throw Error("COPILOT_UNSUPPORTED_CLAIM");
  return value as CopilotResult;
}
export function coverageLabel(r: CopilotResult, k: CopilotMetric) {
  const n = r.summary[k];
  if (n === null) return "未读取";
  const c = r.summary.coverage.filter((c) => c.tool === metricTools[k]);
  return c.some((c) => !c.complete) ? `至少 ${n}` : String(n);
}
export function evidenceRefs(e: CopilotEvidence[]) {
  return e
    .slice(0, 40)
    .map((v) => ({
      kind: v.kind,
      id: v.id,
      fingerprint: v.fingerprint,
      ...(v.kind === "policy" ? { case_id: v.facts.case_id } : {}),
    }));
}
