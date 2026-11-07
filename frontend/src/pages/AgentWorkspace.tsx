import { useCallback, useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router'
import { useAuth } from '../state/Auth'
import { useMounted } from '../state/useResource'
import { ApiError, errorMessage } from '../api/client'
import type { Run, Thread } from '../api/agentWorkflow'
import { uuidPattern, recoverable, recommendation } from '../api/agentWorkflow'
import RunTimeline from '../components/RunTimeline'
import RecoveryPanel from '../components/RecoveryPanel'
import WorkflowConfirmationCard from '../components/WorkflowConfirmationCard'
import WorkflowResources from '../components/WorkflowResources'
import PolicyCitation from '../components/PolicyCitation'
import ClarificationCard from '../components/ClarificationCard'
import ProviderPanel from '../components/ProviderPanel'
import ThreadMemory from '../components/ThreadMemory'
import { contextRunInput, freshRecommendationConstraints, type ContextOperation } from '../api/threadContext'
export default function AgentWorkspace() {
  const [params, setParams] = useSearchParams()
  const { user } = useAuth()
  const id = params.get('thread') ?? ''
  const order = params.get('order') ?? ''
  return (
    <Workspace
      key={`${user?.store_id}:${user?.user_id}:${id}`}
      id={id}
      order={uuidPattern.test(order) ? order : ''}
      restore={(thread) => setParams(order ? { thread, order } : { thread })}
    />
  )
}
function Workspace({
  id,
  order,
  restore,
}: {
  id: string
  order: string
  restore: (id: string) => void
}) {
  const { client: api } = useAuth()
  const mounted = useMounted()
  const [thread, setThread] = useState<Thread | null>(null)
  const [historyId, setHistoryId] = useState('')
  const [selectedSet, setSelectedSet] = useState('')
  const [selectedBundle, setSelectedBundle] = useState('')
  const patchOperation = useRef<{request_id: string; expected_version: number; operations: ContextOperation[]} | null>(null)
  const [patchUnknown, setPatchUnknown] = useState(false)
  const [mode, setMode] = useState<'single' | 'multi'>('multi')
  const [message, setMessage] = useState(
    order ? `订单${order}有质量问题，申请退货，再帮我推荐一款500元以内的静音键盘。` : '',
  )
  const [busy, setBusy] = useState(false)
  const [requote, setRequote] = useState(false)
  const [notice, setNotice] = useState('')
  const [revision, setRevision] = useState(0)
  const gate = useRef(false)
  const startOperation = useRef<{
    request_id: string
    message: string
    constraints?: Record<string, unknown>
    expected_context_version: number
    candidate_set_id?: string
    bundle_id?: string
  } | null>(null)
  const [uncertainStart, setUncertainStart] = useState(false)
  const [pendingStartId, setPendingStartId] = useState('')
  const run = pendingStartId
    ? thread?.runs.find((item) => item.request_id === pendingStartId)
    : thread?.runs[0]
  const refreshRun = useCallback(() => setRevision((n) => n + 1), [])
  const apply = (value: Thread) => {
    if (mounted.current) {
      setThread(value)
      setRevision((n) => n + 1)
    }
  }
  useEffect(() => {
    if (!uuidPattern.test(id)) return
    const controller = new AbortController()
    let timer: ReturnType<typeof setTimeout> | undefined
    let reads = 0
    let failures = 0
    async function read() {
      try {
        const value = await api.get<Thread>(`/agent/threads/${id}`, controller.signal)
        if (!controller.signal.aborted) {
          setThread(value)
          const discovering = pendingStartId && !value.runs.some((item) => item.request_id === pendingStartId)
          failures = 0
          if ((busy || value.runs[0]?.status === 'RUNNING') && ++reads < 150)
            timer = setTimeout(() => void read(), discovering ? 350 : 1500)
        }
      } catch (e) {
        if (controller.signal.aborted) return
        if (e instanceof ApiError && (e.status === 0 || e.status >= 500) && ++failures < 4)
          timer = setTimeout(() => void read(), 1500)
        else setNotice(errorMessage(e))
      }
    }
    void read()
    return () => {
      controller.abort()
      clearTimeout(timer)
    }
  }, [api, id, revision, busy, pendingStartId])
  async function perform(action: () => Promise<void>) {
    if (gate.current) return
    gate.current = true
    setBusy(true)
    setNotice('')
    try {
      await action()
    } catch (e) {
      if (mounted.current)
        setNotice(`${errorMessage(e)}${e instanceof ApiError ? ` (${e.code})` : ''}`)
    } finally {
      gate.current = false
      if (mounted.current) setBusy(false)
    }
  }
  async function start(text: string, retry = false, constraints?: Record<string, unknown>) {
    if (!thread || !text.trim()) return
    const op =
      retry && startOperation.current
        ? startOperation.current
        : {
            ...contextRunInput(crypto.randomUUID(), text, thread.context?.version ?? 0,
              selectedSet || (thread.context?.candidate_sets.length === 1 ? thread.context.candidate_sets[0].id : undefined),
              selectedBundle || undefined),
            ...(constraints ? { constraints } : {}),
          }
    startOperation.current = op
    setPendingStartId(op.request_id)
    try {
      if (retry) {
        const existing = await api.get<Thread>(`/agent/threads/${id}`)
        if (existing.runs.some((r) => r.request_id === op.request_id)) {
          apply(existing)
          setUncertainStart(false)
          return
        }
      }
      await api.post<Run>(`/agent/threads/${id}/runs`, op)
      setSelectedSet('')
      setSelectedBundle('')
      setRequote(false)
      apply(await api.get<Thread>(`/agent/threads/${id}`))
      setUncertainStart(false)
    } catch (e) {
      const known = e instanceof ApiError && !e.ambiguous
      setUncertainStart(!known)
      if (known) {
        apply(await api.get<Thread>(`/agent/threads/${id}`))
        startOperation.current = null
        setSelectedSet('')
      setSelectedBundle('')
        if (['STALE_CONTEXT', 'STALE_CANDIDATES'].includes(e.code)) setMessage('')
        throw e
      }
      try {
        const existing = await api.get<Thread>(`/agent/threads/${id}`)
        if (existing.runs.some((r) => r.request_id === op.request_id)) {
          apply(existing)
          setUncertainStart(false)
          return
        }
      } catch {
        /* Preserve request identity for explicit reconciliation. */
      }
      throw e
    } finally {
      setPendingStartId('')
    }
  }
  async function patchMemory(operations?: ContextOperation[]) {
    if (!thread) return
    if (operations) patchOperation.current = { request_id: crypto.randomUUID(), expected_version: thread.context?.version ?? 0, operations }
    if (!patchOperation.current) return
    try {
      await api.request(`/agent/threads/${id}/context`, 'PATCH', patchOperation.current)
      patchOperation.current = null
      setPatchUnknown(false)
      setSelectedSet('')
      setSelectedBundle('')
      apply(await api.get<Thread>(`/agent/threads/${id}`))
    } catch (e) {
      setPatchUnknown(!(e instanceof ApiError) || e.ambiguous)
      apply(await api.get<Thread>(`/agent/threads/${id}`))
      throw e
    }
  }
  async function recover() {
    if (!run) return
    try {
      await api.post(`/agent/threads/${id}/runs/${run.id}/recover`, { request_id: run.request_id })
    } finally {
      apply(await api.get<Thread>(`/agent/threads/${id}`))
    }
  }
  const statusLabels = {
    RUNNING: '工作流正在执行',
    WAITING_INPUT: '等待用户输入或确认',
    COMPLETED: '工作流已完成',
    PARTIAL: '部分成功，请分别核对结果',
    FAILED: '工作流未完成',
  }
  const originalOrder = run?.result?.entity_refs.find(
    (r) => r.kind === 'order' && r.relation === 'original',
  )
  return (
    <main className="page workspace-page">
      <header className="page-header">
        <div>
          <span className="eyebrow">AGENT WORKSPACE</span>
          <h1>每一步，都有据可循</h1>
          <p className="muted">让专业 Agent 协作；关键决定由你确认。</p>
        </div>
        <span className="workflow-badge">持久化工作流</span>
      </header>
      <ProviderPanel runId={run?.id} revision={revision} busy={busy} />
      <RecoveryPanel busy={busy} onRestore={restore} />
      {notice && (
        <div className="notice warning" role="alert">
          {notice}
        </div>
      )}
      {!id ? (
        <section className="panel stack">
          <h2>开启一个新会话</h2>
          <label>
            运行模式
            <select value={mode} onChange={(e) => setMode(e.target.value as 'single' | 'multi')}>
              <option value="multi">Multi · Supervisor 与专业 Agent</option>
              <option value="single">Single · 单 Agent</option>
            </select>
          </label>
          <button
            className="button primary"
            disabled={busy}
            onClick={() =>
              void perform(async () => {
                const created = await api.post<Thread>('/agent/threads', { mode })
                restore(created.id)
              })
            }
          >
            创建 Thread
          </button>
        </section>
      ) : (
        <>
          <section className="panel thread-meta">
            <span className="eyebrow">
              {thread?.mode ?? '…'} / {thread?.status ?? '恢复中'}
            </span>
            <p>
              Thread <code data-testid="thread-id">{id}</code>
            </p>
            <button className="button secondary" onClick={() => setRevision((n) => n + 1)}>
              核对 Thread 状态
            </button>
          </section>
          {thread?.context && <ThreadMemory context={thread.context} busy={busy || patchUnknown || uncertainStart || !!(run && (recoverable(run) || run.status === 'WAITING_INPUT'))}
            selected={selectedSet || (thread.context.candidate_sets.length === 1 ? thread.context.candidate_sets[0].id : '')}
            selectedBundle={selectedBundle} onSelectBundle={setSelectedBundle}
            onSelect={setSelectedSet} onPatch={ops => void perform(() => patchMemory(ops))} />}
          {patchUnknown && <p className="notice warning">偏好更新结果尚未确定。<button className="text-button" disabled={busy} onClick={() => void perform(() => patchMemory())}>核对并重试原偏好请求</button></p>}
          <div className="workspace-grid">
            <div className="workflow-main">
              <form
                className="panel stack"
                onSubmit={(e) => {
                  e.preventDefault()
                  void perform(() => start(message))
                }}
              >
                <label htmlFor="workflow-goal">本次任务</label>
                <textarea
                  id="workflow-goal"
                  maxLength={2000}
                  rows={4}
                  value={message}
                  onChange={(e) => setMessage(e.target.value)}
                  placeholder="例如：找一款300元以内的静音键盘，准备购买，送演示宿舍"
                />
                <button
                  className="button primary"
                  disabled={
                    busy ||
                    !thread ||
                    !message.trim() ||
                    uncertainStart || patchUnknown ||
                    (run && recoverable(run)) ||
                    (run?.status === 'WAITING_INPUT' && !requote)
                  }
                >
                  启动新 Run
                </button>
                {uncertainStart && (
                  <button
                    type="button"
                    className="button secondary"
                    disabled={busy}
                    onClick={() => void perform(() => start(message, true))}
                  >
                    核对并重试原请求
                  </button>
                )}
              </form>
              {run && (
                <>
                  <section className="panel run-summary" data-testid="run-summary">
                    <span className="eyebrow">
                      RUN / {run.result?.execution_mode ?? '执行模式待核对'}
                    </span>
                    <h2>{statusLabels[run.status]}</h2>
                    <strong data-testid="run-status">{run.status}</strong>
                    <small>run_id {run.id}</small>
                    <small>模型配置指纹 {run.model_id}</small>
                    {recoverable(run) && (
                      <div className="notice warning">
                        <p>
                          工作流尚未完成，可从持久状态继续原
                          Run。若执行进程仍在运行，服务器会拒绝并发恢复；请稍后核对。
                        </p>
                        <button
                          className="button primary"
                          disabled={busy}
                          onClick={() => void perform(recover)}
                        >
                          恢复原 Run
                        </button>
                      </div>
                    )}
                    {run.result?.execution_mode === 'FIXTURE' && (
                      <p className="notice">
                        Fixture · Fake Model，真实 PostgreSQL 与 Checkpoint；未调用付费模型。
                      </p>
                    )}
                    {run.last_error === 'MODEL_DISABLED' && (
                      <p className="notice">MODEL_DISABLED · 模型未启用</p>
                    )}
                    {run.last_error && run.last_error !== 'MODEL_DISABLED' && (
                      <p>执行错误码 {run.last_error}。业务结果须以下方真实回执为准。</p>
                    )}
                    {run.result?.error_codes.length ? (
                      <p>未完成原因：{run.result.error_codes.join(' · ')}</p>
                    ) : null}
                    {run.result?.unfinished.length ? (
                      <p>待处理任务：{run.result.unfinished.join(' · ')}</p>
                    ) : null}
                    <p className="muted">
                      工作流模型预算计次 {run.budget.models ?? 0} / 12 · 工具 {run.budget.tools ?? 0} / 16 ·
                      未知 Token Usage 以 UNKNOWN 展示。
                    </p>
                    {run.status === 'PARTIAL' && (
                      <>
                        <p>已完成的业务不会因推荐或回答失败而撤销。下方资源来自独立 GET 核对。</p>
                        <button
                          className="button secondary"
                          disabled={busy || recoverable(run)}
                          onClick={() =>
                            void perform(() => {
                              const next = recommendation(run)
                              return start(next.message, false, freshRecommendationConstraints(next.constraints))
                            })
                          }
                        >
                          只重试推荐（新 Run）
                        </button>
                        <p className="muted">
                          原业务引用保留在此会话历史中。如服务器要求先恢复原
                          Run，将显示限制，不修改原状态。
                        </p>
                      </>
                    )}
                  </section>
                  <div hidden={!['WAITING_INPUT', 'RUNNING'].includes(run.status) || !run.pending_confirmation}>
                    {run.pending_confirmation?.proposal_id && (
                      <WorkflowConfirmationCard
                        key={run.pending_confirmation.interrupt_id}
                        run={run}
                        onThread={apply}
                        onRequote={() => {
                          setRequote(true)
                          setNotice('请在本次任务中重新明确需求，再启动新 Run。新快照仍需重新批准。')
                        }}
                      />
                    )}
                    {run.pending_confirmation?.type === 'clarification' && (
                      <ClarificationCard
                        key={`${run.id}:${run.pending_confirmation.interrupt_id}`}
                        run={run}
                        onThread={apply}
                      />
                    )}
                  </div>
                  {run.result?.facts
                    .filter((f) => f.kind === 'proposal')
                    .map((f) => (
                      <p className="notice" key={f.id}>
                        提案 {f.id} · {String(f.data.status)}
                        {f.data.status === 'REJECTED' ? ' · 用户已拒绝，未执行此提案。' : ''}
                      </p>
                    ))}
                  <WorkflowResources
                    refs={run.result?.entity_refs ?? []}
                    revision={String(revision)}
                  />
                  {run.result?.citations.map((c) => (
                    <PolicyCitation
                      key={c.id ?? c.document_id + c.section_id}
                      citation={c}
                      policyVersion={originalOrder?.policy_version ?? ''}
                    />
                  ))}
                  {thread!.runs.slice(1).map((previous) => (
                    <details className="panel" key={previous.id} onToggle={e => { if (e.currentTarget.open) setHistoryId(previous.id) }}>
                      <summary>
                        历史 Run · {previous.status} · {previous.id}
                      </summary>
                      <p className="muted">历史 Run · 商品引用不是当前报价，不能在此批准旧操作。</p>
                      <WorkflowResources refs={previous.result?.entity_refs ?? []} />
                      {historyId === previous.id && <RunTimeline run={previous} />}
                    </details>
                  ))}
                </>
              )}
            </div>
            {pendingStartId && !run && <p role="status">正在查找本次运行的持久记录…</p>}
            {run && (
              <RunTimeline key={run.id} run={run}
                live={busy || run.status === 'RUNNING' || run.status === 'WAITING_INPUT'}
                onStatusChange={refreshRun}
              />
            )}
          </div>
        </>
      )}
    </main>
  )
}
