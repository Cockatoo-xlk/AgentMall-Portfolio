import { useEffect, useRef, useState } from "react";
import { errorMessage } from "../api/client";
import {
  coverageLabel,
  evidenceRefs,
  parseCopilotResult,
} from "../api/merchantCopilot";
import type {
  CopilotMetric,
  CopilotResult,
  ReviewSuggestion,
} from "../api/merchantCopilot";
import { useAuth } from "../state/Auth";
import "./merchantCopilot.css";

type Open = (kind: string, id: string) => void;
const toolLabels: Record<string, string> = {
  list_merchant_orders: "读取本店订单",
  get_merchant_order: "读取订单快照",
  list_merchant_after_sales: "读取本店售后",
  get_merchant_after_sales: "读取售后详情",
  list_merchant_products: "读取商品与库存",
  list_catalog_index_jobs: "读取索引任务",
  get_applicable_policy: "读取适用公开政策",
  summarize_operations: "确定性汇总",
};
const metricLabels: Record<CopilotMetric, string> = {
  paid_orders: "已支付待发货",
  requested_cases: "等待审核的售后",
  out_of_stock: "缺货商品",
  low_stock: "低库存商品",
  index_pending: "待处理索引任务",
};

export function CopilotResultView({
  result: r,
  onOpen,
  onFocus,
  disabled = false,
}: {
  result: CopilotResult;
  onOpen: Open;
  onFocus?: (id: string) => void;
  disabled?: boolean;
}) {
  return (
    <section className="stack" aria-label="运营分析结果">
      <p className="notice warning">
        MOCK_TRANSPORT ·
        AI建议，未经商家执行。只读分析，不自动发货、审核、退款或运行索引。
      </p>
      {r.status === "NEEDS_INPUT" && (
        <p role="status">
          需要进一步说明：请选择一笔售后或输入订单、库存、索引相关问题。
        </p>
      )}
      <section className="panel stack">
        <h3>本次已读取范围的经营摘要</h3>
        <div className="copilot-metrics">
          {(Object.keys(metricLabels) as CopilotMetric[]).map((k) => (
            <article className="resource-card" key={k}>
              <small>{metricLabels[k]}</small>
              <strong>{coverageLabel(r, k)}</strong>
            </article>
          ))}
        </div>
        <p className="muted">
          低库存阈值：可用库存1–5。未查询显示“未读取”；分页未完成显示下界，不是全店总数。
        </p>
        {r.summary.coverage.map((c, i) => (
          <small key={i}>
            {toolLabels[c.tool]} · 状态筛选 {c.status_filter ?? "全部"} · 已读取{" "}
            {c.scanned} 条 ·{" "}
            {c.complete ? "该查询范围已读完" : "部分数据，仍有记录未读取"}
          </small>
        ))}
      </section>
      <section className="panel stack">
        <h3>证据支持的待办建议</h3>
        <p>
          已识别 {r.summary.eligible_todo_count} 项，展示{" "}
          {r.summary.shown_todo_count} 项
          {r.summary.advice_truncated ? "；其余建议未展示" : ""}
          。仅在已读取记录中排序，不代表全店紧急程度。
        </p>
        {!r.suggestions.length && (
          <p>当前没有模型选出的可执行待办建议；不表示未读取范围没有待办。</p>
        )}
        {r.suggestions.map((s) => (
          <article className="resource-card stack" key={s.evidence_key}>
            <strong>{s.content}</strong>
            <span className="badge">
              {s.status} · v{s.version}
            </span>
            <small className="id-text">记录 {s.record_id}</small>
            <small>读取于 {s.read_at}</small>
            <p>{s.action}</p>
            <small>
              {s.priority_rule}。{s.risk}
            </small>
            <button
              className="button secondary small"
              type="button"
              disabled={disabled}
              onClick={() =>
                onOpen(
                  s.type === "SHIP"
                    ? "order"
                    : s.type === "REVIEW"
                      ? "case"
                      : "catalog",
                  s.record_id,
                )
              }
            >
              查看原业务记录
            </button>
            {s.type === "REVIEW" && onFocus && (
              <button
                className="button secondary small"
                type="button"
                disabled={disabled}
                onClick={() => onFocus(s.record_id)}
              >
                为这笔售后草拟说明
              </button>
            )}
          </article>
        ))}
      </section>
      <section className="panel stack">
        <h3>业务证据与公开政策</h3>
        {r.evidence.map((e) => (
          <details className="resource-card" key={e.key}>
            <summary>
              {e.kind} · {e.status} · v{e.version} · {e.id}
            </summary>
            <small>读取时间 {e.read_at}</small>
            <pre className="copilot-facts">
              {JSON.stringify(e.facts, null, 2)}
            </pre>
            {e.kind === "case" && onFocus && (
              <button
                className="button secondary"
                type="button"
                disabled={disabled}
                onClick={() => onFocus(e.id)}
              >
                选择此售后并提问
              </button>
            )}
          </details>
        ))}
      </section>
      <small>
        模型调用 {r.metrics.model_calls}/2 · 工具 {r.metrics.tool_calls}/7 ·
        数据页 {r.metrics.db_pages} · 耗时 {r.metrics.latency_ms.toFixed(1)}ms ·
        无证据声明 {r.metrics.unsupported_claims} · 业务写入{" "}
        {r.metrics.business_writes}。这些是Fixture流程指标，不是实际LLM准确率。
      </small>
    </section>
  );
}
export default function MerchantCopilot({
  caseId,
  onOpen,
  onUseDraft,
}: {
  caseId?: string;
  onOpen: Open;
  onUseDraft: (draft: ReviewSuggestion) => void;
}) {
  const { client } = useAuth();
  const [mode, setMode] = useState("LOADING"),
    [question, setQuestion] = useState(
      caseId
        ? "这笔售后申请为什么值得优先处理？帮我草拟一段审核说明。"
        : "帮我看看目前有哪些订单需要发货，以及还有哪些退货申请等待审核。",
    );
  const [focus, setFocus] = useState<string | undefined>(caseId),
    [events, setEvents] = useState<
      { phase: string; name?: string; records?: number }[]
    >([]),
    [result, setResult] = useState<CopilotResult | null>(null),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [stale, setStale] = useState(false),
    [checking, setChecking] = useState(false),
    [draft, setDraft] = useState("");
  const current = useRef<AbortController | null>(null),
    lock = useRef(false);
  useEffect(() => {
    const c = new AbortController();
    client
      .get<{ model_mode: string }>("/merchant/copilot/meta", c.signal)
      .then((v) => {
        if (!c.signal.aborted) setMode(v.model_mode);
      })
      .catch((e) => {
        if (!c.signal.aborted) setError(errorMessage(e));
      });
    return () => {
      c.abort();
      current.current?.abort();
    };
  }, [client]);
  async function analyze() {
    if (lock.current || mode !== "MOCK_TRANSPORT" || !question.trim()) return;
    lock.current = true;
    const c = new AbortController();
    current.current = c;
    setBusy(true);
    setError("");
    setEvents([]);
    setResult(null);
    setDraft("");
    setStale(false);
    let received = false;
    try {
      await client.stream(
        "/merchant/copilot/analyze/stream",
        (kind, data) => {
          if (c.signal.aborted) return;
          const v = JSON.parse(data);
          if (kind === "progress") {
            if (
              !v ||
              typeof v.phase !== "string" ||
              v.status !== "COMPLETED" ||
              (v.name && !Object.hasOwn(toolLabels, v.name))
            )
              throw Error("分析事件格式不符");
            setEvents((old) => [
              ...old,
              { phase: v.phase, name: v.name, records: v.records },
            ]);
          }
          if (kind === "analysis_error")
            throw Error("只读分析未完成或证据被拒绝，请核对后重新分析。");
          if (kind === "result") {
            const parsed = parseCopilotResult(v);
            setResult(parsed);
            setDraft(parsed.review_draft?.text ?? "");
            received = true;
          }
        },
        c.signal,
        { question: question.trim(), ...(focus ? { case_id: focus } : {}) },
      );
      if (!received)
        throw Error("连接已中断，未收到完整分析；未执行业务操作。");
    } catch (e) {
      if (!c.signal.aborted) setError(errorMessage(e));
    } finally {
      lock.current = false;
      if (!c.signal.aborted) setBusy(false);
    }
  }
  async function check(fill = false) {
    if (!result || checking || lock.current) return;
    lock.current = true;
    const c = new AbortController();
    current.current = c;
    setChecking(true);
    setError("");
    try {
      const refs =
        fill && result.review_draft
          ? result.evidence.filter((e) =>
              result.review_draft!.evidence_keys.includes(e.key),
            )
          : result.evidence;
      if (!refs.length) return;
      const v = await client.request<{ unchanged: boolean }>(
        "/merchant/copilot/check",
        "POST",
        { references: evidenceRefs(refs) },
        undefined,
        c.signal,
      );
      if (c.signal.aborted) return;
      setStale(!v.unchanged);
      if (v.unchanged && fill && result.review_draft)
        onUseDraft({ ...result.review_draft, text: draft });
    } catch (e) {
      if (!c.signal.aborted) {
        setStale(true);
        setError(errorMessage(e));
      }
    } finally {
      lock.current = false;
      if (!c.signal.aborted) setChecking(false);
    }
  }
  return (
    <section className="stack merchant-copilot" aria-label="AI运营助手">
      <div className="panel stack">
        <h2>AI运营助手</h2>
        <p className="notice">
          {mode} ·
          建议与业务执行分离。不会自动审核、发货、退款、发布或运行索引。
        </p>
        <label className="field">
          运营问题
          <textarea
            maxLength={500}
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            disabled={busy || checking}
          />
        </label>
        <div className="inline-actions">
          <button
            className="button secondary small"
            disabled={busy || checking}
            onClick={() => {
              setFocus(undefined);
              setQuestion("哪些商品缺货或低库存，哪些索引任务需要处理？");
            }}
          >
            库存与索引示例
          </button>
          <button
            className="button primary"
            disabled={
              busy || checking || mode !== "MOCK_TRANSPORT" || !question.trim()
            }
            onClick={() => void analyze()}
          >
            {busy ? "正在读取与分析…" : "开始只读分析"}
          </button>
        </div>
        {focus && (
          <p className="id-text">
            当前明确选择的售后 {focus}{" "}
            <button
              className="text-button"
              disabled={busy || checking}
              onClick={() => setFocus(undefined)}
            >
              清除选择
            </button>
          </p>
        )}
        {mode === "MODEL_DISABLED" && (
          <p>
            普通API未启用商家模型。仅经过明确配置的本地Mock演示可运行；没有真实LLM调用。
          </p>
        )}
      </div>
      <section className="panel stack" aria-label="实际分析进度">
        <h3>实际分析进度</h3>
        {!events.length && (
          <p>{busy ? "等待已完成的计划与工具回执…" : "尚未执行分析"}</p>
        )}
        <ol>
          {events.map((e, i) => (
            <li key={i}>
              {e.name
                ? toolLabels[e.name]
                : ((
                    {
                      plan: "受控工具计划",
                      recommend: "建议选择",
                      validate: "证据验证",
                    } as Record<string, string>
                  )[e.phase] ?? e.phase)}{" "}
              · 已完成{e.records !== undefined ? ` · ${e.records}条记录` : ""}
            </li>
          ))}
        </ol>
      </section>
      {error && (
        <p className="notice error" role="alert">
          {error}
        </p>
      )}
      {result && (
        <>
          <CopilotResultView
            result={result}
            onOpen={onOpen}
            disabled={busy || checking}
            onFocus={(id) => {
              setFocus(id);
              setQuestion(
                "这笔售后申请为什么值得优先处理？帮我草拟一段审核说明。",
              );
            }}
          />
          {stale && (
            <p className="notice warning" role="alert">
              数据已变化或无法核实，旧建议不能填入，请重新分析。
            </p>
          )}
          <button
            className="button secondary"
            disabled={checking || busy || !result.evidence.length}
            onClick={() => void check()}
          >
            核对证据是否已变化
          </button>
          {result.review_draft && (
            <section className="panel stack" aria-label="审核说明草稿">
              <h3>AI审核说明草稿 · 未经商家执行</h3>
              <p>
                规则资格快照、当前Case状态和公开政策分别展示；草稿不代表批准或拒绝。
              </p>
              <label className="field">
                可编辑审核草稿
                <textarea
                  maxLength={1000}
                  disabled={checking}
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                />
              </label>
              <div className="inline-actions">
                <button
                  className="button secondary"
                  onClick={() =>
                    void navigator.clipboard
                      .writeText(draft)
                      .catch(() => setError("复制失败，可手动选取草稿。"))
                  }
                >
                  复制草稿
                </button>
                <button
                  className="button primary"
                  disabled={checking || stale || !draft.trim()}
                  onClick={() => void check(true)}
                >
                  核对后仅填入审核表单
                </button>
              </div>
              <p>填入后仍须在原售后页面独立点击“审核通过”或“审核拒绝”。</p>
            </section>
          )}
        </>
      )}
    </section>
  );
}
