import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router'
import { PackageCheck, PackageSearch, ArrowUpRight } from 'lucide-react'
import { useAuth } from '../state/Auth'
import { useMounted, useResource } from '../state/useResource'
import { errorMessage } from '../api/client'
import { addressLabel, formatDate, money, orderStatusLabel } from '../api/format'
import type { Order, Page } from '../api/types'
export function OrderDetail() {
  const { id } = useParams()
  const {
    data: order,
    error,
    loading,
    reload,
  } = useResource<Order>(id ? `/orders/${encodeURIComponent(id)}` : null)
  if (loading)
    return (
      <main className="page loading" role="status">
        正在核对订单…
      </main>
    )
  if (error || !order)
    return (
      <main className="page stack">
        <div role="alert" className="notice error">
          {error ?? '订单不可用'}
        </div>
        <button className="button secondary" onClick={reload}>
          重试查询订单
        </button>
      </main>
    )
  return (
    <main className="page narrow-page">
      <div className="order-success">
        <PackageCheck size={38} />
        <span className="eyebrow">ORDER CONFIRMED</span>
        <h1>订单已创建</h1>
        <p>
          已取得服务端订单信息，当前状态：<strong>{orderStatusLabel(order.status)}</strong>。
        </p>
      </div>
      <section className="panel stack">
        <div className="section-heading">
          <h2>订单详情</h2>
          <span className="badge">{orderStatusLabel(order.status)}</span>
        </div>
        <dl className="details-list">
          <div>
            <dt>订单编号</dt>
            <dd className="id-text">{order.id}</dd>
          </div>
          <div>
            <dt>创建时间</dt>
            <dd>{formatDate(order.created_at)}</dd>
          </div>
          <div>
            <dt>收货地址</dt>
            <dd>{addressLabel(order.address_label)}</dd>
          </div>
        </dl>
        <div className="checkout-items">
          {order.items.map((item) => (
            <div className="proposal-item" key={item.product_id}>
              <div>
                <strong>{item.name_snapshot}</strong>
                <p className="muted">
                  下单单价 {money(item.unit_price_cents)} · 数量 {item.quantity}
                </p>
              </div>
              <strong>{money(item.unit_price_cents * item.quantity)}</strong>
            </div>
          ))}
        </div>
        <div className="total-row">
          <span>订单金额</span>
          <strong className="price">{money(order.total_cents)}</strong>
        </div>
        <div className="notice">本页展示订单信息。模拟支付、取消和物流操作请使用受控 API。</div>
        <div className="inline">
          <Link className="button primary" to="/orders">
            查看我的订单
          </Link>
          <Link className="button secondary" to={`/proposals/${order.proposal_id}`}>
            查看原提案
          </Link>
          <button className="button secondary" onClick={reload}>
            刷新订单状态
          </button>
        </div>
      </section>
    </main>
  )
}
export default function Orders() {
  const { client } = useAuth(),
    alive = useMounted()
  const [rows, setRows] = useState<Order[]>([]),
    [cursor, setCursor] = useState<string | null>(null),
    [busy, setBusy] = useState(false),
    [error, setError] = useState<string | null>(null),
    [revision, setRevision] = useState(0)
  useEffect(() => {
    const controller = new AbortController()
    setBusy(true)
    setError(null)
    setRows([])
    client
      .get<Page<Order>>('/orders?limit=8', controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) {
          setRows(data.items)
          setCursor(data.next_cursor)
        }
      })
      .catch((err) => {
        if (!controller.signal.aborted) setError(errorMessage(err))
      })
      .finally(() => {
        if (!controller.signal.aborted) setBusy(false)
      })
    return () => controller.abort()
  }, [client, revision])
  async function more() {
    if (!cursor || busy) return
    setBusy(true)
    try {
      const data = await client.get<Page<Order>>(`/orders?limit=8&cursor=${cursor}`)
      if (alive.current) {
        setRows((old) => [...old, ...data.items])
        setCursor(data.next_cursor)
      }
    } catch (err) {
      if (alive.current) setError(errorMessage(err))
    } finally {
      if (alive.current) setBusy(false)
    }
  }
  return (
    <main className="page">
      <div className="page-header">
        <div>
          <span className="eyebrow">YOUR ORDERS</span>
          <h1>每一笔，都有记录。</h1>
          <p className="muted">查看订单快照与当前状态，所有结果均来自服务端。</p>
        </div>
        <button
          className="button secondary"
          onClick={() => setRevision((n) => n + 1)}
          disabled={busy}
        >
          刷新订单列表
        </button>
      </div>
      {error && (
        <div className="notice error" role="alert">
          {error}
        </div>
      )}
      {busy && <p role="status">正在加载订单…</p>}
      {!busy && !rows.length && !error && (
        <div className="panel empty-state">
          <PackageSearch size={38} />
          <h2>还没有订单</h2>
          <p>先选好商品，再确认你的购买提案。</p>
          <Link className="button primary" to="/">
            去挑选商品
          </Link>
        </div>
      )}
      <div className="order-grid">
        {rows.map((order) => (
          <Link className="panel order-card" to={`/orders/${order.id}`} key={order.id}>
            <div className="section-heading">
              <span className="badge">{orderStatusLabel(order.status)}</span>
              <ArrowUpRight size={18} />
            </div>
            <h2>{order.items.map((i) => i.name_snapshot).join('、')}</h2>
            <p className="muted">{formatDate(order.created_at)}</p>
            <p className="id-text">{order.id}</p>
            <div className="total-row">
              <span>{order.items.reduce((n, i) => n + i.quantity, 0)} 件商品</span>
              <strong className="price">{money(order.total_cents)}</strong>
            </div>
          </Link>
        ))}
      </div>
      {cursor && (
        <button className="button secondary load-more" disabled={busy} onClick={() => void more()}>
          加载更多订单
        </button>
      )}
    </main>
  )
}
