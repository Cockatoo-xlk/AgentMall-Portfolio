import { useEffect, useState } from 'react'
import { Activity, FlaskConical, GitCompareArrows, ShieldCheck } from 'lucide-react'
import {
  architectures,
  categories,
  filterEpisodes,
  formatMetric,
  parseStudioReport,
  statuses,
} from '../api/evaluationStudio'
import type { Episode, EpisodeFilters, Metric, StudioReport } from '../api/evaluationStudio'
import './evaluationStudio.css'

const reportUrl = '/evals/studio-v1.json'
const names = { single: 'Single Agent', multi: 'Multi-Agent' }
const groupLabels: Record<string, string> = {
  A1: '商品推荐',
  A2: '购买提案',
  A3: '订单查询',
  B1: '售后处理',
  B2: '退货与替代',
  S1: '安全边界',
  R1: '执行恢复',
  E1: '异常路径',
}
const effectLabels: Record<string, string> = {
  orders: '订单',
  aftersales_cases: '售后申请',
  payments: '付款',
  refunds: '退款',
  support_tickets: '人工工单',
}
const safetyLabels: Record<string, string> = {
  unauthorized_business_write_count: '未授权业务写入',
  missing_expected_confirmation_count: '缺失预期确认',
  observed_safety_rejection_count: '观察到的安全拦截',
  unsupported_fact_claim_count: '无依据事实断言',
}

function percent(value: Metric) {
  return typeof value === 'number' ? formatMetric(value * 100, '%', 1) : value
}
function date(value: string) {
  return value === 'UNKNOWN'
    ? value
    : new Date(value).toLocaleString('zh-CN', {
        timeZone: 'Asia/Shanghai',
        dateStyle: 'medium',
        timeStyle: 'medium',
      })
}
function counts(successes: Metric, denominator: Metric) {
  return `${formatMetric(successes)} / ${formatMetric(denominator)}`
}

function Comparison({ report }: { report: StudioReport }) {
  const comparison = report.comparison
  const delta = comparison.multi_minus_single
  return (
    <section className="panel eval-section" id="eval-comparison">
      <div className="eval-section-head">
        <div>
          <span className="eyebrow">
            <GitCompareArrows size={16} /> 02 / COMPARISON
          </span>
          <h2>配对比较</h2>
          <p className="muted">
            按 Task ID 与重复编号配对。失败、未运行及 Harness 失败均保留在原计划分母。
          </p>
        </div>
        <span className="eval-badge">
          {comparison.paired_episodes} 对 · {comparison.cluster_count} 个任务簇
        </span>
      </div>
      <div className="eval-comparison-grid">
        <div className="eval-table-wrap">
          <table className="eval-table">
            <caption>按类别的 Oracle 通过数 / 计划数</caption>
            <thead>
              <tr>
                <th scope="col">任务类别</th>
                <th scope="col">Single</th>
                <th scope="col">Multi</th>
              </tr>
            </thead>
            <tbody>
              {categories
                .filter((key) => architectures.some((arch) => comparison[arch].per_category[key]))
                .map((key) => (
                  <tr key={key}>
                    <th scope="row">
                      <code>{key}</code> {groupLabels[key]}
                    </th>
                    {architectures.map((arch) => {
                      const result = comparison[arch].per_category[key]
                      return (
                        <td key={arch}>
                          {result ? counts(result.successes, result.denominator) : 'NOT_APPLICABLE'}
                        </td>
                      )
                    })}
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
        <div className="eval-delta">
          <span className="eyebrow">MULTI − SINGLE</span>
          <h3>观察到的差值</h3>
          <dl className="eval-pairs">
            <div>
              <dt>Oracle 通过率</dt>
              <dd>{formatMetric(delta.success_rate * 100, ' pp', 1)}</dd>
            </div>
            <div>
              <dt>配对平均机器耗时</dt>
              <dd>{formatMetric(delta.mean_machine_seconds, ' s', 3)}</dd>
            </div>
            <div>
              <dt>模型调用总量</dt>
              <dd>{formatMetric(delta.model_calls)}</dd>
            </div>
            <div>
              <dt>工具调用总量</dt>
              <dd>{formatMetric(delta.tool_calls)}</dd>
            </div>
          </dl>
          <div className="eval-bootstrap">
            <h4>任务簇 Bootstrap · 95% 区间</h4>
            <strong>{delta.success_ci95.map(percent).join(' 至 ')}</strong>
            <p>
              通过率差值按 Task ID 抽样 {comparison.bootstrap.repetitions.toLocaleString('en-US')}{' '}
              次，同任务的重复运行留在同一簇。区间只描述本批记录。
            </p>
          </div>
        </div>
      </div>
    </section>
  )
}

function FailureExplorer({ report }: { report: StudioReport }) {
  const [source, setSource] = useState<'recorded' | 'historical'>('recorded')
  const [filters, setFilters] = useState<EpisodeFilters>({
    verdict: 'attention',
  })
  const reviewed = report.historical_live?.reviewed_failure
  const historical: Episode[] = reviewed
    ? [
        {
          ...reviewed,
          repetition_id: null,
          category: 'B2',
          success: false,
          error_class: 'UNKNOWN',
          oracle_rules: ['UNKNOWN'],
          machine_seconds: 'UNKNOWN',
          model_calls: 'UNKNOWN',
          tool_calls: 'UNKNOWN',
          observed_safety_rejections: 'UNKNOWN',
          business_effects:
            reviewed.business_effects === 'UNKNOWN' ? {} : reviewed.business_effects,
        },
      ]
    : []
  const all = source === 'historical' ? historical : report.episodes
  const rows = filterEpisodes(all, filters)
  const edit = (key: keyof EpisodeFilters, value: string) =>
    setFilters((old) => ({ ...old, [key]: value }))
  return (
    <section className="panel eval-section" id="eval-explorer">
      <div className="eval-section-head">
        <div>
          <span className="eyebrow">
            <Activity size={16} /> 03 / FAILURE EXPLORER
          </span>
          <h2>失败与终态诊断</h2>
          <p className="muted">
            Oracle 判定独立于 Run 终态。某些场景预期安全拒绝或保留已提交的部分结果。
          </p>
        </div>
        <span className="eval-badge" aria-live="polite">
          {rows.length} / {all.length} 条记录
        </span>
      </div>
      <div className="eval-filters">
        <label>
          证据来源
          <select
            value={source}
            onChange={(e) => {
              setSource(e.target.value === 'historical' ? 'historical' : 'recorded')
              setFilters({ verdict: 'attention' })
            }}
          >
            <option value="recorded">本报告配对记录</option>
            {reviewed && <option value="historical">历史 Live 已公开失败</option>}
          </select>
        </label>
        <label>
          Task ID
          <input
            value={filters.task ?? ''}
            onChange={(e) => edit('task', e.target.value)}
            placeholder="例如 B2_03"
          />
        </label>
        <label>
          场景类别
          <select value={filters.category ?? ''} onChange={(e) => edit('category', e.target.value)}>
            <option value="">全部类别</option>
            {categories.map((key) => (
              <option key={key} value={key}>
                {key} · {groupLabels[key]}
              </option>
            ))}
          </select>
        </label>
        <label>
          Agent 架构
          <select
            value={filters.architecture ?? ''}
            onChange={(e) => edit('architecture', e.target.value)}
          >
            <option value="">全部架构</option>
            {architectures.map((arch) => (
              <option key={arch} value={arch}>
                {names[arch]}
              </option>
            ))}
          </select>
        </label>
        <label>
          Run 终态
          <select value={filters.status ?? ''} onChange={(e) => edit('status', e.target.value)}>
            <option value="">全部终态</option>
            {statuses.map((status) => (
              <option key={status}>{status}</option>
            ))}
          </select>
        </label>
        <label>
          Oracle 判定
          <select
            value={filters.verdict ?? 'attention'}
            onChange={(e) => edit('verdict', e.target.value)}
          >
            <option value="attention">失败或非完成终态</option>
            <option value="failed">仅 Oracle 未通过</option>
            <option value="all">全部记录</option>
          </select>
        </label>
      </div>
      {source === 'historical' && (
        <p className="eval-caution">
          历史汇总只公开了一条逐任务失败。列表未覆盖全部历史失败，原始 Oracle 原因未提供。
        </p>
      )}
      <div className="eval-records">
        {rows.length === 0 && <p className="eval-caution">没有匹配的记录。</p>}
        {rows.map((row) => (
          <details
            className="eval-record"
            key={`${row.task_id}:${row.repetition_id}:${row.architecture}`}
          >
            <summary>
              <div>
                <code>{row.task_id}</code>
                <small>
                  {names[row.architecture]} · {row.category} · 重复 {row.repetition_id ?? 'UNKNOWN'}
                </small>
              </div>
              <span className="eval-state">{row.run_status}</span>
              <span className={`eval-badge ${row.success ? 'eval-pass' : 'eval-warning'}`}>
                {row.success
                  ? 'Oracle 通过'
                  : row.run_status === 'NOT_RUN'
                    ? '未运行'
                    : 'Oracle 未通过'}
              </span>
            </summary>
            <div className="eval-record-body">
              <dl className="eval-pairs">
                <div>
                  <dt>错误分类</dt>
                  <dd>{row.error_class}</dd>
                </div>
                <div>
                  <dt>Oracle 原因</dt>
                  <dd>
                    {row.oracle_rules.join(' · ') || (row.success ? '无违规规则' : 'UNKNOWN')}
                  </dd>
                </div>
                {row.error_code && (
                  <div>
                    <dt>已审查错误码</dt>
                    <dd>{row.error_code}</dd>
                  </div>
                )}
                <div>
                  <dt>安全拦截</dt>
                  <dd>{formatMetric(row.observed_safety_rejections)}</dd>
                </div>
              </dl>
              <div>
                <h4>已知业务副作用 · 新增记录</h4>
                <dl className="eval-effects">
                  {Object.entries(effectLabels).map(([key, label]) => (
                    <div key={key}>
                      <dt>{label}</dt>
                      <dd>{formatMetric(row.business_effects[key])}</dd>
                    </div>
                  ))}
                </dl>
              </div>
            </div>
          </details>
        ))}
      </div>
    </section>
  )
}

function EvidencePanel({ report }: { report: StudioReport }) {
  const { run, historical_live: live } = report
  const fixture = report.comparison.evidence_class === 'FIXTURE_EVALUATION'
  return (
    <section className="panel eval-section" id="eval-evidence">
      <div className="eval-section-head">
        <div>
          <span className="eyebrow">
            <ShieldCheck size={16} /> 04 / EVIDENCE
          </span>
          <h2>证据与适用范围</h2>
        </div>
        <a className="button secondary" href={reportUrl} download>
          下载脱敏 JSON
        </a>
      </div>
      <div className="eval-comparison-grid">
        <dl className="eval-provenance">
          <div>
            <dt>Evaluation Run ID</dt>
            <dd>{run.run_id}</dd>
          </div>
          <div>
            <dt>执行源码 Git SHA</dt>
            <dd>
              <code>{run.git_commit}</code>
            </dd>
          </div>
          <div>
            <dt>数据集 SHA-256</dt>
            <dd>
              <code>{run.dataset_sha256}</code>
            </dd>
          </div>
          <div>
            <dt>Manifest</dt>
            <dd>
              <code>{run.manifest_sha256}</code>
            </dd>
          </div>
          <div>
            <dt>时间（北京时间）</dt>
            <dd>
              {date(run.started_at)} → {date(run.completed_at)}
            </dd>
          </div>
          <div>
            <dt>Provider 请求（本批次）</dt>
            <dd>{formatMetric(report.comparison.paid_provider_requests)}</dd>
          </div>
          <div>
            <dt>环境</dt>
            <dd>
              {run.environment.os} {run.environment.architecture} · Python {run.environment.python}{' '}
              · PostgreSQL {run.environment.postgresql}
            </dd>
          </div>
        </dl>
        <div className="eval-evidence-notes">
          <h3>如何读这份报告</h3>
          <p>Fixture 覆盖合成任务、工具路径和业务 Oracle。真实模型推理质量需要独立的 Live 评测。</p>
          <p>
            历史 Live Pilot 对应旧版本和同一组开发任务，不能作为当前 V2 的验证。
            {fixture && (
              <>
                {' '}
                随附 Fixture 批次的真实模型验证为 <code>NOT_RUN</code>。
              </>
            )}
          </p>
          <p>
            <code>UNKNOWN</code> 表示无可靠记录，<code>NOT_APPLICABLE</code> 表示该指标不适用，数字
            0 表示记录到零。
          </p>
          <p>机器耗时使用评测器记录，人工等待、平台账单和端到端生产时延需另行测量。</p>
        </div>
      </div>
      {live && (
        <div className="eval-live-evidence">
          <span className="eval-badge eval-warning">历史 Live · 已审查汇总</span>
          <h3>两个开发集 Pilot</h3>
          <div className="eval-table-wrap">
            <table className="eval-table">
              <thead>
                <tr>
                  <th scope="col">历史运行</th>
                  <th scope="col">Single</th>
                  <th scope="col">Multi</th>
                  <th scope="col">Provider 请求（两架构合计）</th>
                </tr>
              </thead>
              <tbody>
                {(['first', 'second'] as const).map((key, index) => (
                  <tr key={key}>
                    <th scope="row">Pilot {index + 1}</th>
                    <td>{counts(live[key].single_success, live[key].tasks_per_architecture)}</td>
                    <td>{counts(live[key].multi_success, live[key].tasks_per_architecture)}</td>
                    <td>{formatMetric(live[key].model_requests)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="muted">
            汇总未提供完整逐任务记录。运行 Git SHA {live.git_commit} · 数据集哈希{' '}
            {live.dataset_sha256} · 平台账单 {formatMetric(live.actual_bill_cny)}。
          </p>
        </div>
      )}
    </section>
  )
}

export default function EvaluationStudio() {
  const [report, setReport] = useState<StudioReport | null>(null)
  const [error, setError] = useState(false)
  const [retry, setRetry] = useState(0)
  useEffect(() => {
    const controller = new AbortController()
    fetch(reportUrl, { signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error('Report not available')
        return response.json()
      })
      .then((value: unknown) => {
        if (!controller.signal.aborted) setReport(parseStudioReport(value))
      })
      .catch(() => {
        if (!controller.signal.aborted) setError(true)
      })
    return () => controller.abort()
  }, [retry])

  return (
    <main className="page eval-studio">
      <header className="eval-hero">
        <div>
          <span className="eyebrow">
            <FlaskConical size={17} /> AGENTMALL / ENGINEERING
          </span>
          <h1>Agent Evaluation Studio</h1>
          <p>
            追踪同任务配对、业务 Oracle 与失败证据。
            {report?.comparison.evidence_class === 'FIXTURE_EVALUATION' &&
              'Fixture 成绩只衡量本次离线任务。'}
          </p>
        </div>
        {report && (
          <div className="eval-hero-source">
            <span className="eval-badge">
              {report.comparison.evidence_class === 'FIXTURE_EVALUATION'
                ? 'Fixture · 离线评测'
                : 'Live · 计划与执行记录'}
            </span>
            <code>{report.run.run_id}</code>
            <code title={report.run.git_commit}>Git {report.run.git_commit.slice(0, 12)}</code>
          </div>
        )}
      </header>
      {error ? (
        <div className="panel eval-section" role="alert">
          <p>评测报告不可用或格式不正确。</p>
          <button
            className="button secondary"
            onClick={() => {
              setError(false)
              setRetry((value) => value + 1)
            }}
          >
            重新读取
          </button>
        </div>
      ) : !report ? (
        <p className="panel eval-section" role="status">
          正在读取评测报告…
        </p>
      ) : (
        <>
          <nav className="eval-jump" aria-label="评测工作台章节">
            <a href="#eval-overview">总览</a>
            <a href="#eval-comparison">配对比较</a>
            <a href="#eval-explorer">失败诊断</a>
            <a href="#eval-evidence">证据</a>
          </nav>
          <section className="eval-overview" id="eval-overview">
            <div className="eval-section-head">
              <div>
                <span className="eyebrow">01 / OVERVIEW</span>
                <h2>执行总览</h2>
              </div>
              <span className="eval-badge">
                {report.comparison.cluster_count} 个任务 · {report.episodes.length} 个计划 Episode
              </span>
            </div>
            <div className="eval-overview-grid">
              {architectures.map((arch) => {
                const stats = report.comparison[arch]
                return (
                  <article className="panel eval-score" key={arch}>
                    <div className="eval-score-top">
                      <h3>{names[arch]}</h3>
                      <span>ORACLE PASS</span>
                    </div>
                    <div className="eval-rate">
                      <strong>{percent(stats.success_rate)}</strong>
                      <span>{counts(stats.successes, stats.denominator)} 个计划 Episode</span>
                    </div>
                    <progress
                      aria-label={`${names[arch]} Oracle 通过率`}
                      value={stats.success_rate}
                      max={1}
                    />
                    <dl className="eval-score-metrics">
                      <div>
                        <dt>P50 机器耗时</dt>
                        <dd>{formatMetric(stats.machine_latency_p50, ' s', 3)}</dd>
                      </div>
                      <div>
                        <dt>P95 机器耗时</dt>
                        <dd>{formatMetric(stats.machine_latency_p95, ' s', 3)}</dd>
                      </div>
                      <div>
                        <dt>模型调用</dt>
                        <dd>{formatMetric(stats.model_calls)}</dd>
                      </div>
                      <div>
                        <dt>工具调用</dt>
                        <dd>{formatMetric(stats.tool_calls)}</dd>
                      </div>
                    </dl>
                    <p className="muted">
                      部分终态 {stats.partial_count} · 未运行 {stats.not_run_count} · Harness 失败{' '}
                      {stats.harness_failure_count}
                    </p>
                    <p className="muted">平台账单 {formatMetric(stats.actual_bill_cny)}</p>
                  </article>
                )
              })}
              <article className="panel eval-score eval-safety">
                <div className="eval-score-top">
                  <h3>
                    <ShieldCheck size={19} /> 安全诊断
                  </h3>
                  <span>SQL ORACLE</span>
                </div>
                <div className="eval-table-wrap">
                  <table className="eval-table">
                    <thead>
                      <tr>
                        <th scope="col">诊断项</th>
                        <th scope="col">Single</th>
                        <th scope="col">Multi</th>
                      </tr>
                    </thead>
                    <tbody>
                      {Object.entries(safetyLabels).map(([key, label]) => (
                        <tr key={key}>
                          <th scope="row">{label}</th>
                          {architectures.map((arch) => (
                            <td key={arch}>
                              {formatMetric(report.comparison[arch].diagnostics[key])}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <p className="muted">安全拦截是 Guard 的观察记录，计数独立于已提交的违规写入。</p>
              </article>
            </div>
          </section>
          <Comparison report={report} />
          <FailureExplorer report={report} />
          <EvidencePanel report={report} />
        </>
      )}
    </main>
  )
}
