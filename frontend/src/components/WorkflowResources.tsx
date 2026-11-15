import { Link } from 'react-router'
import type { EntityRef } from '../api/agentWorkflow'
import { useResource } from '../state/useResource'
import { addressLabel, money } from '../api/format'
import { attributeLabels, attributeValue } from '../api/catalog'
import type { Address, SnapshotItem } from '../api/types'
export interface BusinessResource {
  id: string
  status?: string
  name?: string
  price_cents?: number
  policy_version?: string
  resolution?: string
  resolution_summary?: string
  order_id?: string
  total_cents?: number
  address_label?: Address
  items?: SnapshotItem[]
  available?: number
  attributes?: Record<string, string>
  catalog_version?: number
  reason_code?: string
}
export function BusinessResourceDetails({ reference, data }: { reference: EntityRef; data: BusinessResource }) {
  const ref = reference
  return <>
    <h3>{data.name ?? data.status}</h3>
    <small>{ref.id} · {ref.relation === 'original' ? '原业务引用' : '工作流资源引用'}</small>
    {data.price_cents !== undefined && <p>{money(data.price_cents)}</p>}
    {ref.kind === 'product' && <>
      <p>当前可用库存：{data.available ?? 'UNKNOWN'}</p>
      {data.catalog_version !== undefined && <small>目录版本 {data.catalog_version}</small>}
      {Object.entries(data.attributes ?? {}).map(([key, value]) => <p key={key}>{attributeLabels[key] ?? key}：{attributeValue(value)}</p>)}
    </>}
    {ref.kind === 'order' && <>
      <p>订单状态：{data.status ?? 'UNKNOWN'}{data.status === 'PENDING_PAYMENT' ? ' · 订单已创建，等待支付；尚未付款。' : ''}</p>
      {data.total_cents !== undefined && <p>订单金额 {money(data.total_cents)}</p>}
      {data.address_label && <p>地址：{addressLabel(data.address_label)}</p>}
      {data.items && <ul>{data.items.map(item => <li key={item.product_id}>{item.name_snapshot} × {item.quantity} · 单价 {money(item.unit_price_cents)}</li>)}</ul>}
    </>}
    {ref.kind === 'case' && <>
      <p>{data.status === 'REQUESTED' ? '已创建售后申请，等待审核；尚未退款。' : `售后状态：${data.status ?? 'UNKNOWN'}`}</p>
      {data.order_id && <p>原订单：{data.order_id}</p>}
      {data.reason_code && <p>申请原因：{data.reason_code}</p>}
    </>}
    {ref.kind === 'ticket' && <p>人工工单状态：{data.status}。{data.resolution ? `处理结论：${data.resolution}。` : ''}工单处理不代表自动退款。</p>}
    {data.policy_version && <small>政策版本 {data.policy_version}</small>}
    {ref.kind === 'order' && <Link to={`/orders/${ref.id}`}>查看真实订单</Link>}
    {ref.kind === 'product' && <Link to={`/products/${ref.id}`}>查看商品</Link>}
    {ref.kind === 'case' && <Link to={`/after-sales?case=${ref.id}`}>查看售后状态</Link>}
  </>
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
      {data ? <BusinessResourceDetails reference={ref} data={data} /> : (
        !error && <p>正在核对业务资源…</p>
      )}
      {data && <small role="status" data-testid="resource-verification">独立 GET 已核对；刷新只读取资源，不重新提交业务。</small>}
      <button className="text-button" onClick={reload}>
        核对最新状态
      </button>
    </article>
  )
}
