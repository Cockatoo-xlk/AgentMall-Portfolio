import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router'
import { useAuth } from '../state/Auth'
import { ApiError, errorMessage } from '../api/client'
import { timelineSummary } from '../api/timelineSummary'
import { mergeEvents } from '../api/agentWorkflow'
import type { Run, RunEvent, EventPage } from '../api/agentWorkflow'
const labels: Record<string, string> = {
  run_created: 'Run 启动',
  run_activated: '激活执行',
  route_decision: 'Supervisor 路由',
  handoff: 'Specialist Handoff',
  tool: '工具调用',
  model_start: 'LLM 请求',
  model_end: 'LLM 返回',
  specialist_result: '专业任务结果',
  business_receipt: '真实业务回执',
  resume_received: 'Resume',
  run_state: '运行状态',
  node_completed: '节点完成',
}
type Connection = 'connecting' | 'live' | 'reconnecting' | 'history'
const connectionLabels: Record<Connection, string> = {
  connecting: '连接实时进度…',
  live: '实时接收',
  reconnecting: '实时连接中断，正在补读并重连',
  history: '已持久化记录',
}
const statuses = ['RUNNING', 'WAITING_INPUT', 'COMPLETED', 'PARTIAL', 'FAILED']

export default function RunTimeline({ run, live = false, onStatusChange }: {
  run: Run
  live?: boolean
  onStatusChange?: () => void
}) {
  const { client: api } = useAuth()
  const [events, setEvents] = useState<RunEvent[]>([])
  const [error, setError] = useState('')
  const [connection, setConnection] = useState<Connection>('history')
  const [reload, setReload] = useState(0)
  const cursor = useRef(0)
  useEffect(() => {
    const controller = new AbortController()
    const { signal } = controller
    const path = `/agent/runs/${run.id}/events`
    let timer: ReturnType<typeof setTimeout> | undefined
    let retry = 1000
    function append(items: RunEvent[]) {
      if (signal.aborted) return false
      const fresh = items.filter((event) => event.seq > cursor.current)
      if (fresh.length === 0) return false
      if (fresh.some((event, i) => event.seq !== cursor.current + i + 1))
        throw new ApiError(0, 'EVENT_GAP')
      cursor.current = fresh[fresh.length - 1].seq
      setEvents((old) => mergeEvents(old, fresh))
      return true
    }
    async function readHistory() {
      let changed = false
      while (!signal.aborted) {
        const page = await api.get<EventPage>(`${path}?after_seq=${cursor.current}&limit=50`, signal)
        append(page.items)
        changed ||= page.items.some((e) => ['run_state', 'run_activated', 'resume_received'].includes(e.event_type))
        if (page.items.length < 50) break
      }
      return changed
    }
    function denied(e: unknown) {
      return e instanceof ApiError && [401, 403, 404].includes(e.status)
    }
    async function read() {
      let terminal = false
      try {
        if (live) {
          await api.stream(`${path}/stream?after_seq=${cursor.current}`, (kind, data) => {
            if (signal.aborted) return
            if (kind === 'run_event') {
              const event = JSON.parse(data) as RunEvent
              if (append([event]) && event.event_type === 'run_state') onStatusChange?.()
            }
            if (kind === 'run_status') {
              const { status } = JSON.parse(data)
              if (!statuses.includes(status)) throw new ApiError(0, 'INVALID_STREAM')
              terminal = !['RUNNING', 'WAITING_INPUT'].includes(status)
              if (status !== run.status) onStatusChange?.()
            }
            setConnection('live')
            setError('')
            retry = 1000
          }, signal)
          if (signal.aborted) return
          if (terminal) {
            setConnection('history')
            return
          }
        } else {
          await readHistory()
          if (!signal.aborted) setError('')
          return
        }
      } catch (e) {
        if (signal.aborted) return
        // A proxy may serve the legacy API while the SSE route is unavailable.
        if (!live || (e instanceof ApiError && [401, 403].includes(e.status))) {
          setError(errorMessage(e))
          setConnection('history')
          return
        }
      }
      setConnection('reconnecting')
      try {
        const changed = await readHistory()
        if (signal.aborted) return
        setError('')
        if (changed) onStatusChange?.()
      } catch (e) {
        if (signal.aborted) return
        setError(errorMessage(e))
        if (denied(e)) {
          setConnection('history')
          return
        }
      }
      if (!signal.aborted) {
        timer = setTimeout(() => void read(), retry)
        retry = Math.min(5000, retry * 2)
      }
    }
    async function initialize() {
      // An explicit refresh must still exercise the legacy GET contract, even
      // while SSE is available. Preserve its error until the user reconciles.
      if (reload > 0) {
        try {
          await readHistory()
          if (signal.aborted) return
          setError('')
        } catch (e) {
          if (!signal.aborted) {
            setError(errorMessage(e))
            setConnection('history')
          }
          return
        }
      }
      await read()
    }
    setConnection(live ? 'connecting' : 'history')
    void initialize()
    return () => {
      controller.abort()
      clearTimeout(timer)
    }
  }, [api, run.id, run.status, live, onStatusChange, reload])
  async function download() {
    try {
      const pages: unknown[] = []
      let after = 0
      for (let i = 0; i < 40; i++) {
        const page = await api.get<EventPage>(
          `/agent/runs/${run.id}/trace?after_seq=${after}&limit=100`,
        )
        pages.push(page)
        if (page.items.length < 100) break
        after = page.next_seq
      }
      const url = URL.createObjectURL(
        new Blob([JSON.stringify({ pages }, null, 2)], { type: 'application/json' }),
      )
      const link = document.createElement('a')
      link.href = url
      link.download = `run-${run.id}-trace.json`
      link.click()
      URL.revokeObjectURL(url)
    } catch (e) {
      setError(errorMessage(e))
    }
  }
  return (
    <aside className="panel run-timeline">
      <div className="section-heading">
        <div>
          <span className="eyebrow">PERSISTED EVENTS</span>
          <h2>执行时间线</h2>
        </div>
        <span>{events.length} 条</span>
      </div>
      <p className="muted">记录决策路径、工具与回执，不展示模型内部思维。</p>
      <div className="inline-actions">
        <button className="button secondary" onClick={() => setReload((n) => n + 1)}>
          刷新事件
        </button>
        <button className="button secondary" onClick={() => void download()}>
          导出脱敏 Trace
        </button>
      </div>
      {error && <p role="alert">事件读取中断，已展示记录保留。{error}</p>}
      <p className="muted" role="status" data-testid="timeline-connection">
        {connectionLabels[connection]}
      </p>
      <ol className="timeline-list">
        {events.map((event) => (
          <li key={`${run.id}:${event.seq}`} data-testid="run-event" data-seq={event.seq}>
            <div className="event-meta">
              <time>{new Date(event.timestamp).toLocaleTimeString()}</time>
              <span>
                #{event.seq} ·{' '}
                {event.agent ??
                  String(
                    event.payload_summary.target ?? event.payload_summary.role ?? 'workflow',
                  )}
              </span>
            </div>
            <strong>
              {event.event_type === 'tool' &&
              event.payload_summary.ok &&
              ['prepare_checkout', 'prepare_return'].includes(
                String(event.payload_summary.name),
              )
                ? '提案创建'
                : event.event_type === 'tool' &&
                    String(event.payload_summary.name).startsWith('retrieve_')
                  ? '证据检索'
                  : event.event_type === 'run_state' &&
                      event.payload_summary.status === 'WAITING_INPUT'
                    ? '等待用户确认 / 补充'
                    : (labels[event.event_type] ?? event.event_type)}
            </strong>
            <small>{event.event_type}</small>
            {timelineSummary(event) && (
              <p data-testid="event-summary">{timelineSummary(event)}</p>
            )}
            {Object.keys(event.payload_summary).length > 0 && (
              <details>
                <summary>结构化记录</summary>
                <pre>{JSON.stringify(event.payload_summary, null, 2)}</pre>
              </details>
            )}
            {event.action_id && <small>action_id {event.action_id}</small>}
            {run.result?.entity_refs
              .filter(
                (ref) =>
                  ref.id === event.payload_summary.resource_id &&
                  ['order', 'case', 'ticket'].includes(ref.kind),
              )
              .map((ref) => (
                <Link
                  key={ref.id}
                  to={
                    ref.kind === 'order'
                      ? `/orders/${ref.id}`
                      : `/after-sales?${ref.kind}=${ref.id}`
                  }
                >
                  核对{ref.kind === 'order' ? '订单' : ref.kind === 'case' ? '售后' : '工单'}
                  回执
                </Link>
              ))}
          </li>
        ))}
      </ol>
    </aside>
  )
}
