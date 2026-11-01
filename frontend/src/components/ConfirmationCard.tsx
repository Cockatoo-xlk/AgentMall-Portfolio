import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router'
import { Clock3, ShieldCheck } from 'lucide-react'
import { useAuth } from '../state/Auth'
import { useCart } from '../state/Cart'
import { useMounted, useResource } from '../state/useResource'
import { confirmAndExecute, readOutcome } from '../api/checkout'
import { ApiError, errorMessage } from '../api/client'
import { addressLabel, formatDate, money, orderStatusLabel } from '../api/format'
import type { Proposal, Confirmation } from '../api/types'
export default function ConfirmationCard({
  proposalId,
  compact = false,
}: {
  proposalId: string
  compact?: boolean
}) {
  const resource = useResource<Proposal>(`/proposals/${encodeURIComponent(proposalId)}`),
    { client } = useAuth(),
    navigate = useNavigate(),
    alive = useMounted()
  const [busy, setBusy] = useState(false),
    [error, setError] = useState<string | null>(null),
    [now, setNow] = useState(Date.now())
  const [requote, setRequote] = useState(false)
  const lock = useRef(false)
  const { refreshAfterCheckout } = useCart()
  const refreshedCart = useRef<string | null>(null)
  useEffect(() => {
    const proposal = resource.data
    if (
      proposal?.action_type !== 'CHECKOUT' ||
      !proposal.result ||
      refreshedCart.current === proposal.proposal_id
    )
      return
    refreshedCart.current = proposal.proposal_id
    // A persisted receipt is already a known order, even before opening its details.
    void refreshAfterCheckout(proposal.proposal_id)
  }, [resource.data, refreshAfterCheckout])
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [])
  async function act(decision: 'approve' | 'reject') {
    if (resource.data?.action_type !== 'CHECKOUT' || lock.current) return
    lock.current = true
    setBusy(true)
    setError(null)
    try {
      if (decision === 'approve') {
        const order = await confirmAndExecute(client, proposalId)
        if (alive.current) navigate(`/orders/${order.id}`)
      } else {
        await client.post<Confirmation>(`/proposals/${proposalId}/confirmations`, {
          decision: 'reject',
        })
        if (alive.current) resource.reload()
      }
    } catch (err) {
      if (alive.current) {
        setError(errorMessage(err))
        if (err instanceof ApiError && err.status === 409) setRequote(true)
        resource.reload()
      }
    } finally {
      lock.current = false
      if (alive.current) setBusy(false)
    }
  }
  async function reconcile() {
    if (resource.data?.action_type !== 'CHECKOUT' || lock.current) return
    lock.current = true
    setBusy(true)
    try {
      const outcome = await readOutcome(client, proposalId)
      if (alive.current) {
        setError(null)
        if (outcome.order) navigate(`/orders/${outcome.order.id}`)
        else resource.reload()
      }
    } catch (err) {
      if (alive.current) setError(errorMessage(err))
    } finally {
      lock.current = false
      if (alive.current) setBusy(false)
    }
  }
  const p = resource.data
  if (resource.loading)
    return (
      <div className="panel loading" role="status">
        正在核对提案…
      </div>
    )
  if (resource.error || !p)
    return (
      <div className="panel stack">
        <div className="notice error" role="alert">
          {resource.error ?? '提案暂时不可用'}
        </div>
        <button className="button secondary" onClick={resource.reload}>
          重试加载提案
        </button>
      </div>
    )
  if (p.action_type !== 'CHECKOUT') {
    const title = {
      MOCK_PAYMENT: '模拟支付提案',
      CANCEL_ORDER: '取消订单提案',
      RETURN_REQUEST: '售后申请提案',
      RETURN_CANCEL: '撤回售后申请提案',
      MOCK_REFUND: '模拟退款提案',
    }[p.action_type]
    const result = p.result
    let resultLabel: string | null = null
    let receiptOrderStatus: string | null = null
    if (result) {
      switch (result.action_type) {
        case 'MOCK_PAYMENT':
          resultLabel = {
            SUCCEEDED: '模拟支付成功',
            DECLINED: '模拟支付已拒付',
            EXPIRED: '订单已过期',
          }[result.status]
          receiptOrderStatus = orderStatusLabel(result.order_status)
          break
        case 'CANCEL_ORDER':
          resultLabel = orderStatusLabel(result.status)
          receiptOrderStatus = resultLabel
          break
        case 'RETURN_REQUEST':
        case 'RETURN_CANCEL':
          resultLabel = { REQUESTED: '售后申请已提交', CANCELLED: '售后申请已撤回' }[result.status]
          break
        case 'MOCK_REFUND':
          resultLabel = '模拟退款成功'
          receiptOrderStatus = orderStatusLabel(result.order_status)
          break
      }
    }
    const caseId =
      result && 'case_id' in result
        ? result.case_id
        : 'case_id' in p.canonical_payload
          ? p.canonical_payload.case_id
          : null
    return (
      <section className="panel confirmation-card stack">
        <div className="section-heading">
          <h2>{title}</h2>
          <span className="badge">{resultLabel ?? '只读提案'}</span>
        </div>
        <div className="notice">此操作使用受控 API。本页仅展示提案和回执信息。</div>
        <dl className="details-list">
          <div>
            <dt>订单编号</dt>
            <dd className="id-text">{p.canonical_payload.order_id}</dd>
          </div>
          {'total_cents' in p.canonical_payload && (
            <div>
              <dt>订单金额</dt>
              <dd className="price">{money(p.canonical_payload.total_cents)}</dd>
            </div>
          )}
          {p.action_type === 'MOCK_REFUND' && (
            <div>
              <dt>退款金额</dt>
              <dd className="price">
                {money(p.result?.amount_cents ?? p.canonical_payload.amount_cents)}
              </dd>
            </div>
          )}
          {caseId && (
            <div>
              <dt>售后单编号</dt>
              <dd className="id-text">{caseId}</dd>
            </div>
          )}
          {result?.action_type === 'MOCK_REFUND' && (
            <div>
              <dt>退款编号</dt>
              <dd className="id-text">{result.refund_id}</dd>
            </div>
          )}
          <div>
            <dt>有效期至</dt>
            <dd>{formatDate(p.expires_at)}</dd>
          </div>
          <div>
            <dt>提案编号</dt>
            <dd className="id-text">{p.proposal_id}</dd>
          </div>
          {receiptOrderStatus && (
            <div>
              <dt>回执时订单状态</dt>
              <dd>{receiptOrderStatus}</dd>
            </div>
          )}
        </dl>
        <div className="inline">
          <Link className="button primary" to={`/orders/${p.canonical_payload.order_id}`}>
            查看订单
          </Link>
          <button className="button secondary" onClick={resource.reload}>
            刷新提案状态
          </button>
        </div>
        <p className="muted">回执记录操作完成时的结果，当前订单状态请查看订单详情。</p>
      </section>
    )
  }
  // Local clocks can drift. Only the latest server status decides expiry.
  const expired = p.status === 'EXPIRED'
  const state = p.result
    ? '订单已创建'
    : p.status === 'REJECTED'
      ? '提案已拒绝'
      : expired
        ? '提案已过期'
        : p.confirmation
          ? '已确认，等待核对订单'
          : '等待确认'
  return (
    <section className="panel confirmation-card stack">
      <div className="section-heading">
        <div>
          <span className="eyebrow">PURCHASE PROPOSAL</span>
          <h2>{state}</h2>
        </div>
        <span className="badge">{p.result ? '下单已完成' : '购买提案'}</span>
      </div>
      <p className="muted">这是购买信息快照。提案不等于订单，确认后才会尝试下单。</p>
      <div className="checkout-items">
        {p.canonical_payload.items.map((item) => (
          <div className="proposal-item" key={item.product_id}>
            <div>
              <strong>{item.name_snapshot}</strong>
              <p className="muted">
                单价 {money(item.unit_price_cents)} · 数量 {item.quantity}
              </p>
              <span className="id-text">{item.product_id}</span>
            </div>
            <strong>{money(item.unit_price_cents * item.quantity)}</strong>
          </div>
        ))}
      </div>
      <dl className="details-list">
        <div>
          <dt>提案总价</dt>
          <dd className="price">{money(p.canonical_payload.total_cents)}</dd>
        </div>
        <div>
          <dt>收货地址</dt>
          <dd>{addressLabel(p.canonical_payload.address_label)}</dd>
        </div>
        <div>
          <dt>有效期至</dt>
          <dd>{formatDate(p.expires_at)}</dd>
        </div>
        <div>
          <dt>确认记录</dt>
          <dd>
            {p.confirmation
              ? p.confirmation.decision === 'approve'
                ? '用户已同意'
                : '用户已拒绝'
              : '尚未确认'}
          </dd>
        </div>
        <div>
          <dt>提案编号</dt>
          <dd className="id-text">{p.proposal_id}</dd>
        </div>
      </dl>
      {!p.result && !expired && p.status !== 'REJECTED' && (
        <p className="expiry-note">
          <Clock3 size={15} />
          {Date.parse(p.expires_at) <= now
            ? '本机倒计时已结束。请刷新状态核对，确认时也会先查询服务端有效期。'
            : `约剩 ${Math.ceil((Date.parse(p.expires_at) - now) / 1000)} 秒，最终有效期由服务端判定。`}
        </p>
      )}
      {error && !p.result && p.status !== 'REJECTED' && (
        <div className="notice error" role="alert">
          {error}
        </div>
      )}
      {compact ? (
        <Link className="button primary" to={`/proposals/${p.proposal_id}`}>
          查看并确认提案
        </Link>
      ) : (
        <>
          <div className="confirmation-actions">
            {p.result ? (
              <Link className="button primary" to={`/orders/${p.result.order_id}`}>
                查看订单
              </Link>
            ) : expired || p.status === 'REJECTED' || requote ? (
              <Link className="button primary" to="/cart">
                返回购物车重新报价
              </Link>
            ) : (
              <>
                <button
                  className="button primary"
                  disabled={busy}
                  onClick={() => void act('approve')}
                >
                  {busy ? '正在核对…' : p.confirmation ? '继续创建订单' : '确认并创建订单'}
                </button>
                {!p.confirmation && (
                  <button
                    className="button secondary"
                    disabled={busy}
                    onClick={() => void act('reject')}
                  >
                    拒绝此提案
                  </button>
                )}
              </>
            )}
          </div>
          <div className="inline">
            <button className="button secondary small" disabled={busy} onClick={resource.reload}>
              刷新提案状态
            </button>
            {error && (
              <button
                className="button secondary small"
                disabled={busy}
                onClick={() => void reconcile()}
              >
                核对处理结果
              </button>
            )}
          </div>
        </>
      )}
      <div className="security-note">
        <ShieldCheck size={16} />
        <span>下单结果以服务端回执为准，当前订单状态请查看订单详情。</span>
      </div>
    </section>
  )
}
