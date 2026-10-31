import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router'
import { useAuth } from '../state/Auth'
import { errorMessage } from '../api/client'
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
export default function RunTimeline({ run }: { run: Run }) {
  const { client: api } = useAuth()
  const [events, setEvents] = useState<RunEvent[]>([])
  const [error, setError] = useState('')
  const [stopped, setStopped] = useState(false)
  const [reload, setReload] = useState(0)
  const cursor = useRef(0)
  useEffect(() => {
    const controller = new AbortController()
    let timer: ReturnType<typeof setTimeout> | undefined
    let rounds = 0
    async function read() {
      try {
        const page = await api.get<EventPage>(
          `/agent/runs/${run.id}/events?after_seq=${cursor.current}&limit=50`,
          controller.signal,
        )
        if (controller.signal.aborted) return
        setEvents((old) => mergeEvents(old, page.items))
        cursor.current = Math.max(cursor.current, page.next_seq)
        setError('')
        setStopped(false)
        rounds++
        if (rounds >= 40) {
          setStopped(true)
          return
        }
        if (page.items.length === 50 || run.status === 'RUNNING')
          timer = setTimeout(() => void read(), page.items.length === 50 ? 50 : 1500)
      } catch (e) {
        if (!controller.signal.aborted) {
          setError(errorMessage(e))
          setStopped(true)
        }
      }
    }
    void read()
    return () => {
      controller.abort()
      clearTimeout(timer)
    }
  }, [api, run.id, run.status, run.pending_confirmation?.interrupt_id, reload])
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
      {stopped && <p>轮询已暂停，可手动继续读取。</p>}
      <ol className="timeline-list">
        {events.map((event) => (
          <li key={`${run.id}:${event.seq}`} data-testid="run-event" data-seq={event.seq}>
            <div className="event-meta">
              <time>{new Date(event.timestamp).toLocaleTimeString()}</time>
              <span>
                #{event.seq} ·{' '}
                {event.agent ??
                  String(event.payload_summary.target ?? event.payload_summary.role ?? 'workflow')}
              </span>
            </div>
            <strong>
              {event.event_type === 'tool' &&
              event.payload_summary.ok &&
              ['prepare_checkout', 'prepare_return'].includes(String(event.payload_summary.name))
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
            {Object.keys(event.payload_summary).length > 0 && (
              <pre>{JSON.stringify(event.payload_summary, null, 2)}</pre>
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
                  核对{ref.kind === 'order' ? '订单' : ref.kind === 'case' ? '售后' : '工单'}回执
                </Link>
              ))}
          </li>
        ))}
      </ol>
    </aside>
  )
}
