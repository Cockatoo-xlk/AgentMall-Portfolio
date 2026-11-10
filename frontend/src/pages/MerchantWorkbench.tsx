import { useState } from 'react'
import { Link } from 'react-router'
import { addressLabel, formatDate, money, orderStatusLabel } from '../api/format'
import type {
  AfterSalesCase,
  CaseStatus,
  Order,
  OrderStatus,
  Page,
  ReturnReasonCode,
} from '../api/types'
import MerchantRefund from '../components/MerchantRefund'
import MerchantCatalog from '../components/MerchantCatalog'
import MerchantCopilot from '../components/MerchantCopilot'
import type { ReviewSuggestion } from '../api/merchantCopilot'
import type { RefundDraft } from '../components/MerchantRefund'
import { useAuth } from '../state/Auth'
import { useMerchantAction } from '../state/useMerchantAction'
import { useResource } from '../state/useResource'

const ordersPath = '/merchant/orders'
const casesPath = '/merchant/after-sales'
const orderStatuses: OrderStatus[] = [
  'PENDING_PAYMENT',
  'PAID',
  'SHIPPED',
  'DELIVERED',
  'REFUNDED',
  'CANCELLED',
  'EXPIRED',
]
const caseLabels: Record<CaseStatus, string> = {
  REQUESTED: '待审核',
  APPROVED: '已通过',
  RECEIVED: '已收到退货',
  REFUNDED: '已退款',
  REJECTED: '已拒绝',
  CANCELLED: '已取消',
}
const reasonLabels: Record<ReturnReasonCode, string> = {
  QUALITY_ISSUE: '商品质量问题',
  NOT_NEEDED: '不再需要',
  QUALITY_DISPUTE: '质量争议',
  POLICY_DISPUTE: '政策争议',
  INSUFFICIENT_INFORMATION: '信息不足',
  OTHER: '其他原因',
}

export default function MerchantWorkbench() {
  const { user } = useAuth()
  if (!user)
    return (
      <main className="page empty-state">
        <h1>登录后继续</h1>
        <p>登录商家账号后，可处理所属店铺的订单与售后。</p>
        <Link className="button primary" to="/login" state={{ from: '/merchant' }}>
          去登录
        </Link>
      </main>
    )
  if (user.role !== 'merchant')
    return (
      <main className="page empty-state">
        <h1>仅商家可访问</h1>
        <p>买家账号不能查看或处理商家订单。</p>
        <Link className="button secondary" to="/orders">
          返回我的订单
        </Link>
      </main>
    )
  return <Workbench key={`${user.user_id}:${user.store_id}`} />
}

function Workbench() {
  const [tab, setTab] = useState<'orders' | 'cases' | 'catalog' | 'copilot'>('orders')
  const [orderId, setOrderId] = useState<string | null>(null)
  const [caseId, setCaseId] = useState<string | null>(null)
  const [copilotCase, setCopilotCase] = useState<string>()
  const [reviewSuggestion, setReviewSuggestion] = useState<ReviewSuggestion>()
  // Keep operation identities while inspecting another record in this login.
  const [refunds, setRefunds] = useState<Record<string, RefundDraft>>({})
  return (
    <main className="page merchant-page">
      <header className="page-header">
        <div>
          <span className="eyebrow">MERCHANT OPERATIONS</span>
          <h1>商家工作台</h1>
          <p className="muted">管理本店商品、发货、送达和退货，核对服务端记录。</p>
        </div>
      </header>
      <nav className="inline-actions" aria-label="工作台模块">
        <button
          className={`button ${tab === 'orders' ? 'primary' : 'secondary'}`}
          aria-pressed={tab === 'orders'}
          onClick={() => setTab('orders')}
        >
          订单管理
        </button>
        <button
          className={`button ${tab === 'cases' ? 'primary' : 'secondary'}`}
          aria-pressed={tab === 'cases'}
          onClick={() => setTab('cases')}
        >
          售后管理
        </button>
        <button className={`button ${tab === 'catalog' ? 'primary' : 'secondary'}`} aria-pressed={tab === 'catalog'} onClick={() => setTab('catalog')}>商品管理</button>
        <button className={`button ${tab === 'copilot' ? 'primary' : 'secondary'}`} aria-pressed={tab === 'copilot'} onClick={() => setTab('copilot')}>AI运营助手</button>
      </nav>
      {tab === 'copilot' ? <MerchantCopilot caseId={copilotCase} onOpen={(kind,id)=>{if(kind==='order'){setOrderId(id);setTab('orders')}else if(kind==='case'){setCaseId(id);setTab('cases')}else setTab('catalog')}} onUseDraft={value=>{setReviewSuggestion(value);setCaseId(value.case_id);setTab('cases')}} /> : tab === 'catalog' ? <MerchantCatalog /> : tab === 'orders' ? (
        <OrdersPanel selected={orderId} select={setOrderId} />
      ) : (
        <CasesPanel
          reviewSuggestion={reviewSuggestion}
          askAI={id=>{setCopilotCase(id);setTab('copilot')}}
          selected={caseId}
          select={setCaseId}
          draft={caseId ? refunds[caseId] : undefined}
          saveDraft={(id, update) =>
            setRefunds((previous) => ({ ...previous, [id]: { ...previous[id], ...update } }))
          }
          showOrder={(id) => {
            setOrderId(id)
            setTab('orders')
          }}
        />
      )}
    </main>
  )
}

function useMerchantPage<T>(path: string) {
  const [status, setStatus] = useState('')
  const [cursors, setCursors] = useState<string[]>([])
  const query = new URLSearchParams({ limit: '12' })
  if (status) query.set('status', status)
  const cursor = cursors.at(-1)
  if (cursor) query.set('cursor', cursor)
  const page = useResource<Page<T>>(`${path}?${query}`)
  return {
    ...page,
    status,
    pageNumber: cursors.length + 1,
    filter: (value: string) => {
      setStatus(value)
      setCursors([])
    },
    next: () => {
      const next = page.data?.next_cursor
      if (next) setCursors((previous) => [...previous, next])
    },
    previous: () => setCursors((previous) => previous.slice(0, -1)),
  }
}

function PageControls({
  page,
  hasNext,
  next,
  previous,
}: {
  page: number
  hasNext: boolean
  next: () => void
  previous: () => void
}) {
  return (
    <div className="inline-actions" aria-label="列表分页">
      <button className="button secondary small" disabled={page === 1} onClick={previous}>
        上一页
      </button>
      <span className="muted">第 {page} 页</span>
      <button className="button secondary small" disabled={!hasNext} onClick={next}>
        下一页
      </button>
    </div>
  )
}

function ReadStatus({ loading, error }: { loading: boolean; error: string | null }) {
  if (loading)
    return (
      <p className="muted" role="status">
        正在读取服务端状态…
      </p>
    )
  if (error)
    return (
      <p className="notice error" role="alert">
        {error}
      </p>
    )
  return null
}

function OrdersPanel({
  selected,
  select,
}: {
  selected: string | null
  select: (id: string) => void
}) {
  const page = useMerchantPage<Order>(ordersPath)
  return (
    <div className="merchant-grid">
      <section className="panel stack" aria-label="订单列表">
        <div className="section-heading">
          <h2>本店订单</h2>
          <button className="button secondary small" onClick={page.reload}>
            刷新订单列表
          </button>
        </div>
        <label className="field">
          订单状态
          <select value={page.status} onChange={(event) => page.filter(event.target.value)}>
            <option value="">全部状态</option>
            {orderStatuses.map((status) => (
              <option key={status} value={status}>
                {orderStatusLabel(status)}
              </option>
            ))}
          </select>
        </label>
        <ReadStatus loading={page.loading} error={page.error} />
        {page.data?.items.length === 0 && <p className="muted">没有符合当前筛选的订单。</p>}
        {page.data?.items.map((order) => (
          <article className="merchant-row" key={order.id}>
            <div className="section-heading">
              <strong>{order.items.map((item) => item.name_snapshot).join('、')}</strong>
              <span className="badge">{orderStatusLabel(order.status)}</span>
            </div>
            <p>
              {money(order.total_cents)} · {formatDate(order.created_at)} · v{order.version}
            </p>
            <p className="id-text">{order.id}</p>
            <button
              className="button secondary small"
              aria-label={`查看订单 ${order.id}`}
              aria-pressed={order.id === selected}
              onClick={() => select(order.id)}
            >
              查看订单
            </button>
          </article>
        ))}
        <PageControls
          page={page.pageNumber}
          hasNext={!!page.data?.next_cursor}
          next={page.next}
          previous={page.previous}
        />
      </section>
      {selected ? (
        <OrderDetail key={selected} id={selected} reloadList={page.reload} />
      ) : (
        <section className="panel">
          <h2>订单详情</h2>
          <p className="muted">选择左侧订单查看详情。</p>
        </section>
      )}
    </div>
  )
}

function OrderDetail({ id, reloadList }: { id: string; reloadList: () => void }) {
  const { client } = useAuth()
  const detail = useResource<Order>(`${ordersPath}/${id}`)
  const action = useMerchantAction(() => {
    detail.reload()
    reloadList()
  })
  const order = detail.data
  const event = order?.status === 'PAID' ? 'ship' : order?.status === 'SHIPPED' ? 'deliver' : null
  return (
    <section className="panel stack" aria-label="订单详情">
      <div className="section-heading">
        <h2>订单详情</h2>
        <button className="button secondary small" disabled={action.busy} onClick={detail.reload}>
          刷新订单详情
        </button>
      </div>
      <ReadStatus loading={detail.loading} error={detail.error} />
      {action.error && (
        <p className="notice error" role="alert">
          {action.error}
        </p>
      )}
      {order && (
        <>
          <span className="badge">{orderStatusLabel(order.status)}</span>
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
            <div>
              <dt>当前版本</dt>
              <dd>{order.version}</dd>
            </div>
          </dl>
          {order.items.map((item) => (
            <div className="proposal-item" key={item.product_id}>
              <strong>
                {item.name_snapshot} × {item.quantity}
              </strong>
              <span>{money(item.unit_price_cents * item.quantity)}</span>
            </div>
          ))}
          <div className="total-row">
            <span>订单金额</span>
            <strong>{money(order.total_cents)}</strong>
          </div>
          {event && (
            <button
              className="button primary"
              disabled={action.busy}
              onClick={() =>
                void action.run(async () => {
                  await client.post(`${ordersPath}/${id}/${event}`, {
                    expected_version: order.version,
                  })
                }, true)
              }
            >
              {event === 'ship' ? '发货' : '确认送达'}
            </button>
          )}
        </>
      )}
    </section>
  )
}

function CasesPanel({
  reviewSuggestion,
  askAI,
  selected,
  select,
  showOrder,
  draft,
  saveDraft,
}: {
  reviewSuggestion: ReviewSuggestion | undefined
  askAI: (id: string) => void
  selected: string | null
  select: (id: string) => void
  showOrder: (id: string) => void
  draft: RefundDraft | undefined
  saveDraft: (id: string, update: Partial<RefundDraft>) => void
}) {
  const page = useMerchantPage<AfterSalesCase>(casesPath)
  return (
    <div className="merchant-grid">
      <section className="panel stack" aria-label="售后列表">
        <div className="section-heading">
          <h2>本店售后</h2>
          <button className="button secondary small" onClick={page.reload}>
            刷新售后列表
          </button>
        </div>
        <label className="field">
          售后状态
          <select value={page.status} onChange={(event) => page.filter(event.target.value)}>
            <option value="">全部状态</option>
            {Object.entries(caseLabels).map(([status, label]) => (
              <option key={status} value={status}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <ReadStatus loading={page.loading} error={page.error} />
        {page.data?.items.length === 0 && <p className="muted">没有符合当前筛选的售后申请。</p>}
        {page.data?.items.map((record) => (
          <article className="merchant-row" key={record.id}>
            <div className="section-heading">
              <strong>{reasonLabels[record.reason_code]}</strong>
              <span className="badge">{caseLabels[record.status]}</span>
            </div>
            <p className="id-text">售后 {record.id}</p>
            <p className="id-text">订单 {record.order_id}</p>
            <p className="muted">
              {formatDate(record.created_at)} · v{record.version}
            </p>
            <button
              className="button secondary small"
              aria-label={`查看售后 ${record.id}`}
              aria-pressed={record.id === selected}
              onClick={() => select(record.id)}
            >
              查看售后
            </button>
          </article>
        ))}
        <PageControls
          page={page.pageNumber}
          hasNext={!!page.data?.next_cursor}
          next={page.next}
          previous={page.previous}
        />
      </section>
      {selected ? (
        <CaseDetail
          key={selected}
          reviewSuggestion={reviewSuggestion?.case_id===selected ? reviewSuggestion : undefined}
          askAI={askAI}
          id={selected}
          reloadList={page.reload}
          showOrder={showOrder}
          draft={draft ?? {}}
          saveDraft={(update) => saveDraft(selected, update)}
        />
      ) : (
        <section className="panel">
          <h2>售后详情</h2>
          <p className="muted">选择左侧申请查看详情。</p>
        </section>
      )}
    </div>
  )
}

function CaseDetail({
  reviewSuggestion,
  askAI,
  id,
  reloadList,
  showOrder,
  draft,
  saveDraft,
}: {
  reviewSuggestion: ReviewSuggestion | undefined
  askAI: (id: string) => void
  id: string
  reloadList: () => void
  showOrder: (id: string) => void
  draft: RefundDraft
  saveDraft: (update: Partial<RefundDraft>) => void
}) {
  const { client } = useAuth()
  const detail = useResource<AfterSalesCase>(`${casesPath}/${id}`)
  const [reason, setReason] = useState(reviewSuggestion?.text ?? '')
  const [discardedSuggestion, setDiscardedSuggestion] = useState(false)
  const reload = () => {
    detail.reload()
    reloadList()
  }
  const action = useMerchantAction(reload)
  const record = detail.data
  const staleSuggestion = !!reviewSuggestion && !discardedSuggestion && !!record && record.version !== reviewSuggestion.case_version
  function review(decision: 'approve' | 'reject') {
    if (!record || record.status !== 'REQUESTED' || !reason.trim() || staleSuggestion) return
    void action.run(async () => {
      await client.post(`${casesPath}/${id}/review`, {
        decision,
        reason: reason.trim(),
        expected_version: record.version,
      })
    }, true)
  }

  return (
    <section className="panel stack" aria-label="售后详情">
      <div className="section-heading">
        <h2>售后详情</h2>
        <button className="button secondary small" disabled={action.busy} onClick={detail.reload}>
          刷新售后详情
        </button>
      </div>
      <ReadStatus loading={detail.loading} error={detail.error} />
      {action.error && (
        <p className="notice error" role="alert">
          {action.error}
        </p>
      )}
      {record && (
        <>
          <span className="badge">{caseLabels[record.status]}</span>
          <dl className="details-list">
            <div>
              <dt>售后编号</dt>
              <dd className="id-text">{record.id}</dd>
            </div>
            <div>
              <dt>关联订单</dt>
              <dd className="id-text">{record.order_id}</dd>
            </div>
            <div>
              <dt>申请原因</dt>
              <dd>
                {reasonLabels[record.reason_code]} · {record.description}
              </dd>
            </div>
            {record.review_reason && (
              <div>
                <dt>审核说明</dt>
                <dd>{record.review_reason}</dd>
              </div>
            )}
            <div>
              <dt>当前版本</dt>
              <dd>{record.version}</dd>
            </div>
          </dl>
          <button className="button secondary small" onClick={() => showOrder(record.order_id)}>
            查看关联订单
          </button>
          {record.status === 'REQUESTED' && (
            <>
              <button className="button secondary small" onClick={()=>askAI(id)}>让AI草拟审核说明</button>
              {reviewSuggestion && <p className="notice warning">AI建议，未经商家执行。仍需独立选择审核决定。</p>}
              {staleSuggestion && <p className="notice error" role="alert">售后版本已变化，旧AI草稿不能执行。<button className="text-button" onClick={()=>{setReason('');setDiscardedSuggestion(true)}}>放弃旧建议并重新填写</button></p>}
              <label className="field">
                审核说明
                <textarea
                  value={reason}
                  onChange={(event) => setReason(event.target.value)}
                  maxLength={1000}
                />
              </label>
              <div className="inline-actions">
                <button
                  className="button primary"
                  disabled={action.busy || !reason.trim() || staleSuggestion}
                  onClick={() => review('approve')}
                >
                  审核通过
                </button>
                <button
                  className="button secondary"
                  disabled={action.busy || !reason.trim() || staleSuggestion}
                  onClick={() => review('reject')}
                >
                  审核拒绝
                </button>
              </div>
            </>
          )}
          {record.status === 'APPROVED' && (
            <button
              className="button primary"
              disabled={action.busy}
              onClick={() =>
                void action.run(async () => {
                  await client.post(`${casesPath}/${id}/receive`, {
                    expected_version: record.version,
                  })
                }, true)
              }
            >
              确认收到退货
            </button>
          )}
        </>
      )}
      <MerchantRefund record={record} reload={reload} draft={draft} save={saveDraft} />
    </section>
  )
}
