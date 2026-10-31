import { Link } from 'react-router'
import type { EntityRef } from '../api/agentWorkflow'
import { useResource } from '../state/useResource'
import { money } from '../api/format'
export interface BusinessResource {
  id: string
  status?: string
  name?: string
  price_cents?: number
  policy_version?: string
  resolution?: string
  resolution_summary?: string
  order_id?: string
}
const labels = {
  order: '订单',
  case: '售后申请',
  ticket: '人工工单',
  product: '商品候选',
  proposal: '提案',
}
export default function WorkflowResources({
  refs,
  revision = '',
}: {
  refs: EntityRef[]
  revision?: string
}) {
  const unique = [
    ...new Map(
      refs.filter((r) => r.kind !== 'proposal').map((r) => [`${r.kind}:${r.id}`, r]),
    ).values(),
  ]
  return (
    <div className="resource-grid">
      {unique.map((ref) => (
        <Resource key={`${ref.kind}:${ref.id}:${revision}`} reference={ref} />
      ))}
    </div>
  )
}
function Resource({ reference: ref }: { reference: EntityRef }) {
  const paths = {
    order: 'orders',
    case: 'after-sales',
    ticket: 'support-tickets',
    product: 'products',
    proposal: 'proposals',
  }
  const { data, error, reload } = useResource<BusinessResource>(`/${paths[ref.kind]}/${ref.id}`)
  return (
    <article className="resource-card" data-testid={`resource-${ref.kind}`}>
      <span className="eyebrow">{labels[ref.kind]} · 服务器核对</span>
      {error && <p role="alert">状态尚未核实：{error}</p>}
      {data ? (
        <>
          <h3>{data.name ?? data.status}</h3>
          <small>{ref.id}</small>
          {data.price_cents !== undefined && <p>{money(data.price_cents)}</p>}
          {ref.kind === 'case' && (
            <p>
              {data.status === 'REQUESTED'
                ? '已创建售后申请，等待审核；尚未退款。'
                : `售后状态：${data.status}`}
            </p>
          )}
          {ref.kind === 'ticket' && (
            <p>
              人工工单状态：{data.status}。{data.resolution ? `处理结论：${data.resolution}。` : ''}
              工单处理不代表自动退款。
            </p>
          )}
          {data.policy_version && <small>政策版本 {data.policy_version}</small>}
          {ref.kind === 'order' && <Link to={`/orders/${ref.id}`}>查看真实订单</Link>}
          {ref.kind === 'product' && <Link to={`/products/${ref.id}`}>查看商品</Link>}
          {ref.kind === 'case' && <Link to={`/after-sales?case=${ref.id}`}>查看售后状态</Link>}
        </>
      ) : (
        !error && <p>正在核对业务资源…</p>
      )}
      <button className="text-button" onClick={reload}>
        核对最新状态
      </button>
    </article>
  )
}
