import type { Proposal } from '../api/types'
import { addressLabel, money } from '../api/format'
import { attributeLabels, attributeValue } from '../api/catalog'

export default function WorkflowProposalDetails({ proposal }: { proposal: Proposal }) {
  return <div className="stack" data-testid="proposal-details">
    <small>proposal_id {proposal.proposal_id}</small>
    <p>服务端状态：<strong>{proposal.status}</strong></p>
    {proposal.action_type === 'CHECKOUT' && <>
      <ul>{proposal.canonical_payload.items.map(item => <li key={item.product_id}>
        {item.name_snapshot} × {item.quantity} · 单价 {money(item.unit_price_cents)}
        {Object.entries(item.attributes_snapshot).map(([key, value]) => <small key={key}> · {attributeLabels[key] ?? key}：{attributeValue(value)}</small>)}
      </li>)}</ul>
      <p className="workflow-total">合计 {money(proposal.canonical_payload.total_cents)}</p>
      <p>地址：{addressLabel(proposal.canonical_payload.address_label)} · 政策 {proposal.canonical_payload.policy_version}</p>
    </>}
    {proposal.action_type === 'RETURN_REQUEST' && <>
      <p>原订单：{proposal.canonical_payload.order_id}</p>
      <p>原因：{proposal.canonical_payload.reason_code}</p>
      <p>{proposal.canonical_payload.description}</p>
      <p>政策：{proposal.canonical_payload.policy_version}</p>
      <p>申请成功仅代表 REQUESTED，仍需商家审核；尚未退款。</p>
    </>}
    {proposal.confirmation && <div className="notice" data-testid="proposal-decision">
      <p>此提案的独立决定：{proposal.confirmation.decision === 'approve' ? '已批准' : '已拒绝'} · {proposal.confirmation.consumed_at ? '确认已消费' : '消费状态待业务核对'}</p>
      <small>confirmation_id {proposal.confirmation.confirmation_id}</small>
    </div>}
    {proposal.result && <div className="notice" data-testid="proposal-receipt">
      <p>已提交业务回执：<strong>{proposal.result.status}</strong></p>
      <small>action_id {proposal.result.action_id} · resource_id {proposal.result.resource_id}</small>
    </div>}
    <details><summary>授权快照标识</summary><small>payload_hash {proposal.payload_hash} · Schema {proposal.schema_version}</small></details>
  </div>
}
