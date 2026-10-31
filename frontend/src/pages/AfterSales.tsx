import { useState } from 'react'
import { Link, useSearchParams } from 'react-router'
import { useResource } from '../state/useResource'
import type { EligibilityResult, Order, Page } from '../api/types'
import type { Citation, EntityRef } from '../api/agentWorkflow'
import { uuidPattern } from '../api/agentWorkflow'
import PolicyCitation from '../components/PolicyCitation'
import WorkflowResources from '../components/WorkflowResources'
export default function AfterSales() {
  const [params] = useSearchParams()
  const { data, error, reload } = useResource<Page<Order>>('/orders?limit=50')
  const [orderId, setOrder] = useState('')
  const [reference, setReference] = useState('')
  const [resource, setResource] = useState<EntityRef | null>(() =>
    uuidPattern.test(params.get('case') ?? params.get('ticket') ?? '')
      ? {
          kind: params.get('case') ? 'case' : 'ticket',
          id: (params.get('case') ?? params.get('ticket'))!,
        }
      : null,
  )
  return (
    <main className="page narrow-page">
      <header className="page-header">
        <div>
          <span className="eyebrow">AFTER SALES</span>
          <h1>售后进度，清晰可查</h1>
          <p className="muted">资格以领域服务为准；政策引用提供公开背景。</p>
        </div>
      </header>
      <section className="panel stack">
        <label>
          选择本人订单
          <select value={orderId} onChange={(e) => setOrder(e.target.value)}>
            <option value="">请选择</option>
            {data?.items.map((order) => (
              <option key={order.id} value={order.id}>
                {order.id} · {order.status}
              </option>
            ))}
          </select>
        </label>
        {error && <p role="alert">{error}</p>}
        <button className="text-button" onClick={reload}>
          刷新订单
        </button>
      </section>
      {orderId && <Eligibility key={orderId} id={orderId} />}
      <section className="panel stack">
        <h2>核对售后或人工工单</h2>
        <label>
          Case / Ticket ID
          <input value={reference} onChange={(e) => setReference(e.target.value)} />
        </label>
        <div className="inline-actions">
          <button
            className="button secondary"
            disabled={!uuidPattern.test(reference)}
            onClick={() => setResource({ kind: 'case', id: reference })}
          >
            查询售后申请
          </button>
          <button
            className="button secondary"
            disabled={!uuidPattern.test(reference)}
            onClick={() => setResource({ kind: 'ticket', id: reference })}
          >
            查询人工工单
          </button>
        </div>
      </section>
      {resource && <WorkflowResources key={resource.kind + resource.id} refs={[resource]} />}
    </main>
  )
}
function Eligibility({ id }: { id: string }) {
  const { data: eligibility, error } = useResource<EligibilityResult>(
    `/orders/${id}/after-sales-eligibility?reason_code=QUALITY_ISSUE`,
  )
  const { data: order } = useResource<Order>(`/orders/${id}`)
  const { data: citations, error: citationError } = useResource<{ items: Citation[] }>(
    `/knowledge/search?order_id=${id}&query=${encodeURIComponent('质量问题退货期限')}&mode=hybrid`,
  )
  return (
    <section className="panel stack">
      <h2>售后资格</h2>
      {error && <p role="alert">{error}</p>}
      {eligibility && (
        <>
          <p>
            {eligibility.eligible ? '符合申请条件' : '当前不符合自动申请条件'} ·{' '}
            {eligibility.reason_codes.join(' · ')}
          </p>
          <p>政策版本：{eligibility.policy_version}</p>
          {eligibility.requires_human && <p>需要人工处理；工单完成不代表退款完成。</p>}
          <Link className="button primary" to={`/agent/workspace?order=${id}`}>
            进入工作流准备退货提案
          </Link>
          <p className="muted">将在新工作流中获取提案，申请前须明确确认。</p>
        </>
      )}
      <h3>公开政策条款</h3>
      {citationError && <p>引用暂不可用：{citationError}</p>}
      {citations?.items.length === 0 && <p>未找到可引用的公开条款。</p>}
      {order &&
        citations?.items.map((c) => (
          <PolicyCitation key={c.id} citation={c} policyVersion={order.policy_version} />
        ))}
    </section>
  )
}
