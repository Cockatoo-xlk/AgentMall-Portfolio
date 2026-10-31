import { useRef, useState } from 'react'
import { Link } from 'react-router'
import { Send, Sparkles, ArrowUpRight } from 'lucide-react'
import { useAuth } from '../state/Auth'
import { useMounted } from '../state/useResource'
import { errorMessage } from '../api/client'
import type { AgentResponse } from '../api/types'
import ConfirmationCard from './ConfirmationCard'
export default function ChatPanel() {
  const { client } = useAuth(),
    alive = useMounted()
  const [message, setMessage] = useState(''),
    [busy, setBusy] = useState(false),
    [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<AgentResponse | null>(null),
    [intent, setIntent] = useState<{ request_id: string; message: string } | null>(null)
  const lock = useRef(false)
  async function send(retry = false) {
    if (lock.current || (!retry && !message.trim())) return
    lock.current = true
    setBusy(true)
    setError(null)
    setResult(null)
    const request =
      retry && intent ? intent : { request_id: crypto.randomUUID(), message: message.trim() }
    setIntent(request)
    try {
      const next = await client.post<AgentResponse>('/agent/messages', request)
      if (alive.current) {
        setResult(next)
        setMessage('')
      }
    } catch (err) {
      if (alive.current) setError(errorMessage(err))
    } finally {
      lock.current = false
      if (alive.current) setBusy(false)
    }
  }
  const status = result
    ? {
        done: '已完成核对',
        needs_input: '需要补充信息',
        proposal: '等待确认',
        blocked: '暂时不可用',
        error: '暂时未能完成',
      }[result.status]
    : null
  return (
    <section className="chat-panel">
      <div className="panel assistant-intro">
        <div className="assistant-avatar">
          <Sparkles size={25} />
        </div>
        <span className="eyebrow">A LITTLE HELP, A BETTER CHOICE</span>
        <h2>告诉我，你在找什么？</h2>
        <p>
          预算、偏好、数量与演示收货地址，
          <br />
          把需要说清楚，让选择更轻松。
        </p>
        <button
          className="suggestion"
          disabled={busy}
          onClick={() =>
            setMessage('帮我找一款 300 元以内的静音机械键盘，准备购买一件，送到演示宿舍地址。')
          }
        >
          找一款 300 元以内的静音键盘 <ArrowUpRight size={16} />
        </button>
      </div>
      <div className="panel stack">
        <form
          onSubmit={(e) => {
            e.preventDefault()
            void send()
          }}
          className="stack"
        >
          <label className="field">
            购物需求
            <textarea
              rows={4}
              maxLength={2000}
              required
              value={message}
              disabled={busy}
              onChange={(e) => setMessage(e.target.value)}
              placeholder="例如：预算 300 元，想要一款安静的键盘，购买一件，送到演示宿舍地址。"
            />
          </label>
          <div className="composer-footer">
            <span className="muted small">每次新需求独立处理 · 不保存长期记忆</span>
            <button className="button primary" disabled={busy || !message.trim()}>
              {' '}
              {busy ? '正在处理…' : '发送需求'}
              <Send size={16} />
            </button>
          </div>
        </form>
        <p className="muted small">
          回答一次性返回。需要补充信息时，请重新写出完整需求；当前不支持跨请求记忆。
        </p>
        {busy && <p role="status">正在处理本次需求，请稍候…</p>}
        {error && (
          <div className="notice error" role="alert">
            {error}
            <p>不会自动重复模型请求。</p>
            <button className="button secondary" disabled={busy} onClick={() => void send(true)}>
              重试同一请求
            </button>
          </div>
        )}
        {result && (
          <div className="chat-message" aria-live="polite">
            <span className="badge">{status}</span>
            <p className="assistant-answer">
              {result.status === 'blocked' && result.answer.includes('模型未启用')
                ? 'AI 助手当前未启用；你仍可以通过商品目录和购物车完成购买。'
                : result.answer}
            </p>
            {result.resource_refs.map((ref) => (
              <Link
                className="resource-link"
                key={`${ref.type}:${ref.id}`}
                to={ref.type === 'product' ? `/products/${ref.id}` : `/orders/${ref.id}`}
              >
                {ref.type === 'product' ? '查看商品' : '查看订单'}
                <span className="id-text">{ref.id}</span>
                <ArrowUpRight size={14} />
              </Link>
            ))}
            {result.status === 'needs_input' && (
              <p className="muted small">可在上方输入框补充完整需求后重新发送。</p>
            )}
          </div>
        )}
      </div>
      {result?.proposal_refs.map((id) => (
        <ConfirmationCard key={id} proposalId={id} compact />
      ))}
    </section>
  )
}
