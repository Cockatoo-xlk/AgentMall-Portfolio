import { useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { Link, useNavigate } from 'react-router'
import { ShoppingBag, Trash2, ArrowRight, ShieldCheck } from 'lucide-react'
import { useCart } from '../state/Cart'
import { useAuth } from '../state/Auth'
import { useMounted } from '../state/useResource'
import { ApiError, errorMessage } from '../api/client'
import { money } from '../api/format'
import type { Address, CartItem, CartCheckout, Proposal } from '../api/types'
function Item({ item, locked }: { item: CartItem; locked: boolean }) {
  const { setQuantity, busy } = useCart()
  const [value, setValue] = useState(String(item.quantity))
  function submit(event: FormEvent) {
    event.preventDefault()
    const quantity = Number(value)
    if (Number.isInteger(quantity) && quantity >= 1 && quantity <= 10)
      void setQuantity(item.product_id, quantity)
  }
  return (
    <article className="item-row">
      <div className="cart-icon">
        <ShoppingBag size={26} />
      </div>
      <div className="cart-item-info">
        <Link to={`/products/${item.product_id}`}>{item.name}</Link>
        <p className="muted">
          当前单价 {money(item.unit_price_cents)} · 可用库存 {item.available}
        </p>
        {!item.active && <span className="badge">已下架</span>}
      </div>
      <form className="quantity-form" onSubmit={submit}>
        <input
          type="number"
          min={1}
          max={10}
          required
          aria-label={`数量：${item.name}`}
          value={value}
          onChange={(e) => setValue(e.target.value)}
        />
        <button
          className="button secondary small"
          aria-label={`更新 ${item.name} 数量`}
          disabled={busy || locked || value === String(item.quantity)}
        >
          更新
        </button>
      </form>
      <strong>{money(item.unit_price_cents * item.quantity)}</strong>
      <button
        className="icon-button"
        aria-label={`移除 ${item.name}`}
        disabled={busy || locked}
        onClick={() => void setQuantity(item.product_id, 0)}
      >
        <Trash2 size={18} />
      </button>
    </article>
  )
}
export default function Cart() {
  const { cart, busy, refresh } = useCart(),
    { client } = useAuth(),
    navigate = useNavigate(),
    alive = useMounted()
  const [address, setAddress] = useState<Address>('demo_dorm'),
    [preparing, setPreparing] = useState(false),
    [error, setError] = useState<string | null>(null)
  const [pending, setPending] = useState<{ body: CartCheckout; key: string } | null>(null)
  const [canRequote, setCanRequote] = useState(false)
  const lock = useRef(false)
  async function prepare() {
    if (!cart || lock.current) return
    lock.current = true
    setPreparing(true)
    setError(null)
    const intent = pending ?? {
      body: {
        request_id: crypto.randomUUID(),
        proposal_slot: 'web_cart' as const,
        cart_id: cart.id,
        expected_cart_version: cart.version,
        address_label: address,
      },
      key: `web:prepare:${crypto.randomUUID()}`,
    }
    setPending(intent)
    try {
      const proposal = await client.post<Proposal>('/checkout/proposals', intent.body, intent.key)
      if (alive.current) navigate(`/proposals/${proposal.proposal_id}`)
    } catch (err) {
      const definitiveFailure =
        err instanceof ApiError && !err.ambiguous && [400, 403, 404, 409, 422].includes(err.status)
      if (alive.current) {
        setError(errorMessage(err))
        setCanRequote(definitiveFailure)
      }
      if (definitiveFailure) await refresh()
    } finally {
      lock.current = false
      if (alive.current) setPreparing(false)
    }
  }
  if (!cart)
    return (
      <main className="page">
        <div className="loading" role="status">
          正在核对购物车…
        </div>
        <button className="button secondary" onClick={() => void refresh()}>
          核对购物车
        </button>
      </main>
    )
  return (
    <main className="page">
      <div className="page-header">
        <div>
          <span className="eyebrow">YOUR BAG</span>
          <h1>
            购物车
            <span className="count-label">{cart.items.reduce((n, i) => n + i.quantity, 0)} 件</span>
          </h1>
          <p className="muted">先把喜欢的放在一起，确认提案后才会创建订单。</p>
        </div>
        <Link className="text-link" to="/">
          继续选购 →
        </Link>
      </div>
      {!cart.items.length ? (
        <div className="panel empty-state">
          <ShoppingBag size={40} />
          <h2>购物车还是空的</h2>
          <p>去看看有哪些适合你的桌面好物。</p>
          <Link className="button primary" to="/">
            浏览商品
          </Link>
        </div>
      ) : (
        <div className="split-layout">
          <section className="panel cart-items">
            {cart.items.map((item) => (
              <Item
                key={`${item.product_id}:${item.quantity}:${cart.version}`}
                item={item}
                locked={preparing || (!!pending && !canRequote)}
              />
            ))}
          </section>
          <aside className="panel summary-card stack">
            <h2>准备结算</h2>
            <div className="total-row">
              <span>商品参考合计</span>
              <strong className="price">
                {money(cart.items.reduce((n, i) => n + i.unit_price_cents * i.quantity, 0))}
              </strong>
            </div>
            <label className="field">
              收货地址
              <select
                value={address}
                disabled={!!pending || preparing}
                onChange={(e) => setAddress(e.target.value as Address)}
              >
                <option value="demo_dorm">演示宿舍地址</option>
                <option value="demo_home">演示家庭地址</option>
              </select>
            </label>
            {error && (
              <div className="notice error" role="alert">
                {error}
              </div>
            )}
            <button
              className="button primary"
              disabled={
                busy ||
                preparing ||
                (!pending && cart.items.some((i) => !i.active || i.quantity > i.available))
              }
              onClick={() => void prepare()}
            >
              {preparing ? '正在生成提案…' : pending ? '核对并重试原提案' : '生成购买提案'}
              <ArrowRight size={16} />
            </button>
            {pending && error && canRequote && (
              <button
                className="button secondary"
                disabled={preparing}
                onClick={() => {
                  setCanRequote(false)
                  setPending(null)
                  setError(null)
                }}
              >
                使用最新购物车重新报价
              </button>
            )}
            <div className="security-note">
              <ShieldCheck size={17} />
              <span>下一步会展示服务端报价。生成提案不会预留库存，也不会自动下单。</span>
            </div>
          </aside>
        </div>
      )}
    </main>
  )
}
