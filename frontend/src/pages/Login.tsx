import { useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { Link, useLocation, useNavigate } from 'react-router'
import { ArrowRight, ShieldCheck, ShoppingBag } from 'lucide-react'
import { useAuth } from '../state/Auth'
import { useMounted } from '../state/useResource'
import { ApiError, errorMessage } from '../api/client'
export default function Login() {
  const auth = useAuth(),
    navigate = useNavigate(),
    location = useLocation(),
    alive = useMounted()
  const [login, setLogin] = useState(''),
    [password, setPassword] = useState(''),
    [busy, setBusy] = useState(false),
    [error, setError] = useState<string | null>(null)
  const submitting = useRef(false)
  async function submit(event: FormEvent) {
    event.preventDefault()
    if (submitting.current) return
    submitting.current = true
    setBusy(true)
    setError(null)
    try {
      await auth.login(login.trim(), password)
      if (alive.current) {
        setPassword('')
        const from = location.state?.from
        navigate(
          typeof from === 'string' && from.startsWith('/') && !from.startsWith('//') ? from : '/',
          { replace: true },
        )
      }
    } catch (err) {
      if (alive.current)
        setError(
          err instanceof ApiError && err.status === 401
            ? '账号或密码不正确，请重新输入。'
            : errorMessage(err),
        )
    } finally {
      submitting.current = false
      if (alive.current) setBusy(false)
    }
  }
  return (
    <main className="page login-grid">
      <section className="login-intro">
        <span className="eyebrow">YOUR EVERYDAY, CONSIDERED</span>
        <h1>
          好选择，
          <br />
          从这里开始。
        </h1>
        <p>
          找到适合自己的日常好物。
          <br />
          自己挑选，或让购物助手帮你缩小选择。
        </p>
        <div className="login-illustration">
          <ShoppingBag size={88} strokeWidth={1} />
          <span>AgentMall</span>
        </div>
        <p className="muted">所有商品与交易均为合成演示数据。</p>
      </section>
      <section className="panel login-card">
        <span className="eyebrow">欢迎回来</span>
        <h2>登录 AgentMall</h2>
        <p className="muted">继续你的选购，查看每一笔真实记录。</p>
        {error && (
          <div className="notice error" role="alert">
            {error}
          </div>
        )}
        <form className="stack" onSubmit={submit}>
          <label className="field">
            账号
            <input
              name="login"
              autoComplete="username"
              required
              maxLength={100}
              value={login}
              onChange={(e) => setLogin(e.target.value)}
              placeholder="请输入演示账号"
            />
          </label>
          <label className="field">
            密码
            <input
              name="password"
              type="password"
              autoComplete="current-password"
              required
              maxLength={256}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="请输入账号密码"
            />
          </label>
          <button className="button primary" disabled={busy} type="submit">
            {busy ? '正在登录…' : '登录'}
            <ArrowRight size={16} />
          </button>
        </form>
        <p className="muted small">
          演示账号：buyer1 / buyer2 / merchant
          <br />
          请使用项目提供的演示密码。
        </p>
        <div className="login-note">
          <ShieldCheck size={17} />
          <span>登录状态仅在当前页面内存中保留，刷新后需重新登录。</span>
        </div>
        <Link to="/" className="text-link">
          先逛逛商品 →
        </Link>
      </section>
    </main>
  )
}
