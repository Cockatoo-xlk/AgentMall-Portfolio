import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router'
import { ShieldCheck } from 'lucide-react'
import { useAuth } from '../state/Auth'
import { useMounted } from '../state/useResource'
import { formatDate, money, orderStatusLabel } from '../api/format'
import { errorMessage } from '../api/client'
import {
  createPaymentOperation,
  decidePayment,
  loadPaymentOperation,
  paymentStorageKey,
  preparePayment,
  readPaymentOutcome,
  storePaymentOperation,
} from '../api/payment'
import type { PaymentOperation, PaymentOutcome } from '../api/payment'
import type { Order } from '../api/types'

function message(result: PaymentOutcome) {
  if (result.error && [401, 403, 404].includes(result.error.status))
    return errorMessage(result.error)
  if (result.uncertain) return '付款结果尚未确定，请先核对原提案和订单；继续操作会沿用原请求。'
  const code = result.error?.code
  if (code === 'STALE_VERSION') return '订单版本已变化，请核对最新订单后重新准备付款提案。'
  if (code === 'STALE_PROPOSAL') return '支付提案已过期或失效，请重新准备并确认。'
  if (code === 'INVALID_ORDER_STATE') return '服务端拒绝了当前付款，请核对订单状态和有效期。'
  if (code === 'SNAPSHOT_MISMATCH') return '支付快照与本次订单不一致，已停止操作。'
  if (code === 'DECISION_CONFLICT') return '确认决定已记录，不能改为另一决定。'
  return result.error ? errorMessage(result.error) : null
}
export default function MockPaymentPanel({
  order,
  onOrderRead,
}: {
  order: Order
  onOrderRead: (order: Order) => void
}) {
  const { client, user } = useAuth(),
    alive = useMounted()
  const [operation, setOperation] = useState<PaymentOperation | null>(null)
  const [outcome, setOutcome] = useState<PaymentOutcome | null>(null)
  const [busy, setBusy] = useState(false),
    [storageError, setStorageError] = useState<string | null>(null)
  const lock = useRef(false),
    operationRef = useRef<PaymentOperation | null>(null)
  const key = user ? paymentStorageKey(user, order.id) : null
  function save(op: PaymentOperation) {
    operationRef.current = op
    if (alive.current) setOperation({ ...op })
    if (key) {
      try {
        storePaymentOperation(window.sessionStorage, key, op)
      } catch {
        if (alive.current)
          setStorageError('浏览器无法保存付款引用，请记录提案编号，刷新前先核对结果。')
      }
    }
  }
  function apply(result: PaymentOutcome) {
    if (!alive.current) return
    setOutcome(result)
    if (result.order) onOrderRead(result.order)
  }
  useEffect(() => {
    if (!key) return
    let active = true
    let op: PaymentOperation | null
    try {
      op = loadPaymentOperation(window.sessionStorage, key, order.id)
    } catch (e) {
      setStorageError(errorMessage(e))
      return
    }
    operationRef.current = op
    setOperation(op)
    if (!op) return
    lock.current = true
    setBusy(true)
    // Refresh/login recovery is read-only, including when an approval is already persisted.
    void readPaymentOutcome(client, order.id, op)
      .then((result) => {
        if (!active) return
        setOutcome(result)
        if (result.order) onOrderRead(result.order)
      })
      .finally(() => {
        if (active) {
          lock.current = false
          setBusy(false)
        }
      })
    return () => {
      active = false
    }
  }, [client, key, order.id, onOrderRead])
  async function run(kind: 'prepare' | 'approve' | 'reject' | 'read' | 'new') {
    if (!user || lock.current || (storageError && kind !== 'read')) return
    lock.current = true
    setBusy(true)
    try {
      let op = operationRef.current
      if (kind === 'read' && !op) return
      if (kind === 'new' || !op) {
        setOutcome(null)
        op = createPaymentOperation(order)
        save(op)
      }
      const result =
        kind === 'read'
          ? await readPaymentOutcome(client, order.id, op)
          : kind === 'prepare' || kind === 'new'
            ? await preparePayment(client, order.id, op, save)
            : await decidePayment(
                client,
                order.id,
                op,
                kind === 'approve' ? 'approve' : 'reject',
                save,
              )
      if (result.proposal?.confirmation) {
        op.confirmation_id = result.proposal.confirmation.confirmation_id
        op.decision = result.proposal.confirmation.decision
      }
      if (result.receipt && result.order && !result.error) op.phase = 'complete'
      save(op)
      apply(result)
    } finally {
      lock.current = false
      if (alive.current) setBusy(false)
    }
  }
  const p = outcome?.proposal,
    receipt = outcome?.receipt
  const canPay = order.status === 'PENDING_PAYMENT'
  const terminal =
    p?.status === 'REJECTED' ||
    p?.status === 'EXPIRED' ||
    operation?.phase === 'blocked' ||
    ['STALE_VERSION', 'STALE_PROPOSAL'].includes(outcome?.error?.code ?? '') ||
    receipt?.status === 'DECLINED'
  const snapshotReady = !!p && !receipt && !terminal && !outcome?.error && canPay
  const title = outcome?.uncertain
    ? '付款结果待核对'
    : receipt && outcome?.order && !outcome.error
      ? {
          SUCCEEDED: '模拟支付成功',
          DECLINED: '模拟支付已拒付',
          EXPIRED: '模拟支付已过期',
        }[receipt.status]
      : p?.status === 'REJECTED'
        ? '支付提案已拒绝'
        : p?.status === 'EXPIRED'
          ? '支付提案已过期'
          : p
            ? '请确认模拟付款'
            : '模拟付款'
  return (
    <section className="panel confirmation-card stack payment-panel" aria-label="模拟付款">
      <div className="section-heading">
        <div>
          <span className="eyebrow">MOCK PAYMENT</span>
          <h2>{title}</h2>
        </div>
        {p && <span className="badge">{p.status}</span>}
      </div>
      <div className="notice">
        <strong>仅使用合成数据，不发生真实扣款。</strong>{' '}
        支付提案需要你单独确认，购买时的确认不会用于付款。
      </div>
      {p && (
        <dl className="details-list" data-testid="payment-snapshot">
          <div>
            <dt>快照订单编号</dt>
            <dd className="id-text">{p.canonical_payload.order_id}</dd>
          </div>
          <div>
            <dt>快照支付金额</dt>
            <dd className="price">{money(p.canonical_payload.total_cents)}</dd>
          </div>
          <div>
            <dt>币种</dt>
            <dd>{p.canonical_payload.currency}</dd>
          </div>
          <div>
            <dt>提案有效期至</dt>
            <dd>{formatDate(p.expires_at)}</dd>
          </div>
          <div>
            <dt>服务端提案状态</dt>
            <dd>{p.status}</dd>
          </div>
          <div>
            <dt>支付提案编号</dt>
            <dd className="id-text" data-testid="payment-proposal-id">
              {p.proposal_id}
            </dd>
          </div>
          {p.confirmation && (
            <div>
              <dt>支付确认编号</dt>
              <dd className="id-text">{p.confirmation.confirmation_id}</dd>
            </div>
          )}
        </dl>
      )}
      {receipt && (
        <div className="notice" data-testid="payment-receipt">
          <strong>服务端模拟支付回执：{receipt.status}</strong>
          <p>
            金额 {money(receipt.total_cents)} {receipt.currency} · 回执时间{' '}
            {formatDate(receipt.created_at)}
          </p>
          <p>
            最近一次订单查询：{orderStatusLabel(order.status)}
            。回执记录执行时的结果，当前状态以订单查询为准。
          </p>
          {receipt.payment_id && <p className="id-text">支付编号：{receipt.payment_id}</p>}
          <p className="id-text">动作编号：{receipt.action_id}</p>
          {receipt.status === 'DECLINED' && (
            <p>本次模拟付款已拒付，未创建成功支付记录。重新准备后仍需独立确认。</p>
          )}
        </div>
      )}
      {outcome && message(outcome) && (
        <div className="notice error" role="alert">
          {message(outcome)}
        </div>
      )}
      {storageError && (
        <div className="notice error" role="alert">
          {storageError}
        </div>
      )}
      <div className="confirmation-actions">
        {canPay && !operation && (
          <button
            className="button primary"
            disabled={busy || !user || !!storageError}
            onClick={() => void run('prepare')}
          >
            模拟付款
          </button>
        )}
        {canPay && operation && !p && !terminal && (
          <button
            className="button primary"
            disabled={busy || !!storageError}
            onClick={() => void run('prepare')}
          >
            找回原支付提案
          </button>
        )}
        {snapshotReady && (
          <>
            {operation?.decision !== 'reject' && (
              <button
                className="button primary"
                disabled={busy || !!storageError}
                onClick={() => void run('approve')}
              >
                {p.confirmation?.decision === 'approve' ? '继续已批准的模拟付款' : '批准并模拟付款'}
              </button>
            )}
            {!p.confirmation && operation?.decision !== 'approve' && (
              <button
                className="button danger"
                disabled={busy || !!storageError}
                onClick={() => void run('reject')}
              >
                {operation?.decision === 'reject' ? '继续拒绝本次付款' : '拒绝本次付款'}
              </button>
            )}
          </>
        )}
        {canPay && terminal && !outcome?.uncertain && (
          <button
            className="button primary"
            disabled={busy || !!storageError}
            onClick={() => void run('new')}
          >
            重新准备付款提案
          </button>
        )}
        {operation && (
          <button className="button secondary" disabled={busy} onClick={() => void run('read')}>
            {busy ? '正在核对付款…' : '核对付款结果'}
          </button>
        )}
        {p && (
          <Link className="button secondary" to={`/proposals/${p.proposal_id}`}>
            查看支付提案记录
          </Link>
        )}
      </div>
      {operation && (
        <details>
          <summary>本次付款的恢复引用</summary>
          <dl className="details-list">
            <div>
              <dt>request_id</dt>
              <dd className="id-text">{operation.request_id}</dd>
            </div>
            <div>
              <dt>提案 Idempotency-Key</dt>
              <dd className="id-text">{operation.prepare_key}</dd>
            </div>
            <div>
              <dt>支付 Idempotency-Key</dt>
              <dd className="id-text">{operation.execute_key}</dd>
            </div>
          </dl>
        </details>
      )}
      <p className="security-note">
        <ShieldCheck size={16} /> 有效期由服务端判定。结果未知时先查询原状态，不自动重新付款。
      </p>
    </section>
  )
}
