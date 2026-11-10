import { useEffect, useState } from "react";
import { Link } from "react-router";
import { categoryLabels } from "../api/catalog";
import { money } from "../api/format";
import {
  failureReason,
  parseRetrievalReport,
  pipelineLabels,
  pipelines,
  retrievalMetric as metric,
} from "../api/retrievalQuality";
import type { Pipeline, RetrievalReport } from "../api/retrievalQuality";
import "./evaluationStudio.css";

export function RetrievalQualityView({ report }: { report: RetrievalReport }) {
  const [split, setSplit] = useState<"dev" | "test">("test");
  const [category, setCategory] = useState("all");
  const [arm, setArm] = useState<Pipeline>("hybrid_reranker");
  const [queryId, setQueryId] = useState("");
  const data = report.splits[split],
    groups = [...new Set(data.cases.map((r) => r.category))];
  const rows = data.cases.filter(
    (r) =>
      r.architecture === arm && (category === "all" || r.category === category),
  );
  const selected = queryId || rows[0]?.id;
  const cases = data.cases.filter((r) => r.id === selected);
  const label = (c: string) =>
    (categoryLabels as Record<string, string>)[c] ?? "跨品类";
  return (
    <main className="page eval-studio retrieval-quality">
      <header className="page-header">
        <div>
          <span className="eyebrow">RETRIEVAL QUALITY / 证据与对比</span>
          <h1>检索质量实验室</h1>
          <p>
            同一商品版本、身份、过滤、标签与分母。Lexical 使用 PostgreSQL
            ts_rank_cd，<strong>不是 BM25</strong>。
          </p>
        </div>
        <Link to="/engineering/evals">返回 Agent Evaluation Studio</Link>
      </header>
      <section className="panel stack" aria-label="检索证据来源">
        <h2>
          {report.evidence_class === "REAL_LOCAL_BGE"
            ? "REAL_LOCAL_BGE · 真实本地 CPU"
            : "FIXTURE · 不验证语义质量"}
        </h2>
        <p>
          Cross-Encoder：{report.reranker_evidence} · Provider请求{" "}
          {report.provider_requests} · {report.environment.platform} /{" "}
          {report.environment.architecture}
        </p>
        <p>
          数据集 {report.dataset.dataset_version} · {report.dataset.annotation}
        </p>
        <small>
          Run {report.evaluation_run_id} · {report.executed_at}
        </small>
        <small>
          Git基线 {report.source.git_base_sha} ·{" "}
          {report.source.worktree_dirty
            ? "运行于修改工作树；不能将基线当作修改后提交"
            : "干净工作树"}
          <br />
          实际检索源码内容 SHA256：{report.source.source_tree_sha256}
        </small>
        <p className="notice warning">
          {report.recommendation}
          。本次小型合成单标注者实验不证明统计显著优势；历史Live
          Pilot不等于当前V2模型验收。
        </p>
        {report.known_label_issues.map((issue) => (
          <p className="notice warning" key={issue}>
            {issue}
          </p>
        ))}
        <details>
          <summary>模型、加载与冻结参数</summary>
          <p>
            {report.models.embedding.model_id} ·{" "}
            {report.models.embedding.revision} · 512维 · 进程首次加载{" "}
            {metric(report.models.embedding.cold_load_ms)} ms
          </p>
          <p>
            {report.models.reranker.model_id} ·{" "}
            {report.models.reranker.revision} · 进程首次加载{" "}
            {metric(report.models.reranker.cold_load_ms)} ms · 最长
            {report.models.reranker.max_tokens} Token · batch
            {report.models.reranker.batch_size}
          </p>
          <p>
            候选20 / 最终5 · 旧余弦门槛 {report.dataset.protocol.min_similarity}{" "}
            · DCG {report.dataset.protocol.dcg}
            。OS文件缓存可能已热，不是冷磁盘基准。
          </p>
          {Object.entries(report.dataset.splits).map(([k, v]) => (
            <small key={k}>
              {k} SHA256 {v}
            </small>
          ))}
        </details>
      </section>
      <section className="panel stack" aria-label="四种检索对比">
        <h2>四条 Pipeline</h2>
        <label>
          数据分区
          <select
            aria-label="数据分区"
            value={split}
            onChange={(e) => {
              setSplit(e.target.value as "dev" | "test");
              setQueryId("");
              setCategory("all");
            }}
          >
            <option value="test">冻结 Test</option>
            <option value="dev">Dev（含已披露标注缺口）</option>
          </select>
        </label>
        <div className="eval-table-wrap">
          <table className="eval-table">
            <thead>
              <tr>
                {[
                  "Pipeline",
                  "完成 / 计划",
                  "回答 / 无答案分母",
                  "Recall@5",
                  "MRR@5",
                  "NDCG@5",
                  "候选Recall@20",
                  "候选NDCG上限",
                  "无答案正确率",
                  "P50 ms",
                  "P95 ms",
                  "平均Rerank ms",
                  "逻辑模型调用/查询",
                  "非法 / 过期",
                ].map((x) => (
                  <th key={x}>{x}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {pipelines.map((p) => {
                const s = data.summaries[p];
                return (
                  <tr key={p}>
                    <th>{pipelineLabels[p]}</th>
                    <td>
                      {s.completed_queries} / {s.planned_queries}
                    </td>
                    <td>
                      {s.answer_queries} / {s.no_answer_queries}
                    </td>
                    <td>{metric(s.recall_at_5, true)}</td>
                    <td>{metric(s.mrr_at_5, true)}</td>
                    <td>{metric(s.ndcg_at_5, true)}</td>
                    <td>{metric(s.candidate_recall_at_20, true)}</td>
                    <td>{metric(s.candidate_ndcg_ceiling_at_5, true)}</td>
                    <td>{metric(s.no_answer_accuracy, true)}</td>
                    <td>{metric(s.latency_p50_ms)}</td>
                    <td>{metric(s.latency_p95_ms)}</td>
                    <td>{metric(s.rerank_mean_ms)}</td>
                    <td>{metric(s.model_calls_mean)}</td>
                    <td>
                      {metric(s.illegal_result_count)} /{" "}
                      {metric(s.stale_index_leak_count)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <p>
          未运行、错误或缺失值保持
          UNKNOWN，不记为0、不删失败任务。无候选时不调用重排，平均重排耗时只统计实际执行的查询。模型调用为逻辑encode/score调用，原件另记录实际forward批次。
        </p>
      </section>
      <section className="panel stack">
        <h2>分类与失败诊断</h2>
        <div className="eval-filters">
          <label>
            Pipeline
            <select
              aria-label="检索Pipeline"
              value={arm}
              onChange={(e) => setArm(e.target.value as Pipeline)}
            >
              {pipelines.map((p) => (
                <option key={p} value={p}>
                  {pipelineLabels[p]}
                </option>
              ))}
            </select>
          </label>
          <label>
            品类
            <select
              aria-label="检索品类"
              value={category}
              onChange={(e) => {
                setCategory(e.target.value);
                setQueryId("");
              }}
            >
              <option value="all">全部</option>
              {groups.map((c) => (
                <option key={c} value={c}>
                  {label(c)}
                </option>
              ))}
            </select>
          </label>
        </div>
        <div className="eval-table-wrap">
          <table className="eval-table">
            <thead>
              <tr>
                <th>品类</th>
                <th>完成/计划</th>
                <th>Recall@5</th>
                <th>NDCG@5</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(data.per_category[arm])
                .filter(([c]) => category === "all" || c === category)
                .map(([c, s]) => (
                  <tr key={c}>
                    <th>{label(c)}</th>
                    <td>
                      {s.completed_queries}/{s.planned_queries}
                    </td>
                    <td>{metric(s.recall_at_5, true)}</td>
                    <td>{metric(s.ndcg_at_5, true)}</td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
        <ul aria-label="检索失败案例">
          {rows
            .filter((r) => failureReason(r))
            .map((r) => (
              <li key={r.id}>
                <button
                  className="text-button"
                  type="button"
                  onClick={() => setQueryId(r.id)}
                >
                  {r.id} · {r.query}
                </button>{" "}
                — {failureReason(r)}
              </li>
            ))}
        </ul>
        <label>
          查询详情
          <select
            aria-label="检索查询"
            value={selected}
            onChange={(e) => setQueryId(e.target.value)}
          >
            {rows.map((r) => (
              <option key={r.id} value={r.id}>
                {r.id} · {r.query}
              </option>
            ))}
          </select>
        </label>
      </section>
      <section className="panel stack" aria-label="Top5差异">
        <h2>同一查询的 Top 5</h2>
        {cases[0] && (
          <p>
            {cases[0].query} · 标注依据：{cases[0].annotation_basis}
          </p>
        )}
        <div className="eval-comparison-grid">
          {pipelines.map((p) => {
            const row = cases.find((r) => r.architecture === p);
            return (
              <article key={p} className="resource-card">
                <h3>{pipelineLabels[p]}</h3>
                <p>
                  {row?.status ?? "NOT_RUN"} · 延迟 {metric(row?.pipeline_ms)}{" "}
                  ms
                </p>
                {row?.top5.map((hit, i) => (
                  <div className="stack" key={hit.id}>
                    <strong>
                      {i + 1}. {hit.name}
                    </strong>
                    <small>
                      {money(hit.price_cents)} · v{hit.catalog_version} ·
                      相关等级 {row.grades[hit.id] ?? 0}
                    </small>
                    <small>{hit.id}</small>
                  </div>
                ))}
                {row?.status === "OK" && !row.top5.length && <p>无合法候选</p>}
              </article>
            );
          })}
        </div>
      </section>
    </main>
  );
}
export default function RetrievalQuality() {
  const [report, setReport] = useState<RetrievalReport | null>(null),
    [error, setError] = useState("");
  useEffect(() => {
    const c = new AbortController();
    fetch("/evals/retrieval-v1.json", { signal: c.signal })
      .then((r) => {
        if (!r.ok) throw Error("REPORT_UNAVAILABLE");
        return r.json();
      })
      .then((v) => setReport(parseRetrievalReport(v)))
      .catch(() => {
        if (!c.signal.aborted)
          setError("检索原件缺失或格式不一致；不显示虚构指标。");
      });
    return () => c.abort();
  }, []);
  return error ? (
    <main className="page">
      <p role="alert">{error}</p>
    </main>
  ) : report ? (
    <RetrievalQualityView report={report} />
  ) : (
    <main className="page">
      <p role="status">读取已执行的检索证据…</p>
    </main>
  );
}
