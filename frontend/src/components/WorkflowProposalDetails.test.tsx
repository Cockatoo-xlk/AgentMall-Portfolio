import { renderToStaticMarkup } from 'react-dom/server'
import { expect, it } from 'vitest'
import WorkflowProposalDetails from './WorkflowProposalDetails'
import type { CheckoutProposal, ReturnRequestProposal } from '../api/types'

const checkout: CheckoutProposal = {
  proposal_id: 'purchase-proposal', payload_hash: 'server-snapshot-hash', schema_version: 1,
  action_type: 'CHECKOUT', status: 'PENDING', expires_at: '2099-01-01T00:00:00Z', confirmation: null, result: null,
  canonical_payload: { schema_version: 1, items: [{ product_id: 'p1', name_snapshot: '静音键盘', unit_price_cents: 19900, quantity: 2, attributes_snapshot: { connection: '有线' } }],
    total_cents: 39800, currency: 'CNY', address_label: 'demo_dorm', policy_version: 'policy-v1' },
}

it('renders the exact independent purchase snapshot with quantity and quote identity', () => {
  const html = renderToStaticMarkup(<WorkflowProposalDetails proposal={checkout} />)
  for (const label of ['purchase-proposal', 'server-snapshot-hash', '静音键盘', '× 2', '199.00', '398.00', '有线', '演示宿舍地址', 'policy-v1', 'PENDING']) expect(html).toContain(label)
  expect(html).not.toContain('已提交业务回执')
  expect(html).not.toContain('<button')
})

it('distinguishes a consumed approval and its committed pending-payment receipt', () => {
  const html = renderToStaticMarkup(<WorkflowProposalDetails proposal={{ ...checkout, status: 'EXECUTED',
    confirmation: { confirmation_id: 'confirmation-1', proposal_id: 'purchase-proposal', decision: 'approve', decided_at: '2026-11-15T00:00:00Z', consumed_at: '2026-11-15T00:00:01Z', result_ref: 'order-1' },
    result: { action_id: 'action-1', resource_id: 'order-1', order_id: 'order-1', total_cents: 39800, currency: 'CNY', status: 'PENDING_PAYMENT', created_at: '2026-11-15T00:00:01Z' },
  }} />)
  for (const label of ['confirmation-1', '已批准', '确认已消费', '已提交业务回执', 'action-1', 'order-1', 'PENDING_PAYMENT']) expect(html).toContain(label)
  expect(html).not.toContain('已支付')
})

it('renders a separate return approval snapshot without implying refund or purchase approval', () => {
  const proposal: ReturnRequestProposal = { ...checkout, action_type: 'RETURN_REQUEST', proposal_id: 'return-proposal',
    canonical_payload: { schema_version: 1, order_id: 'original-order', expected_order_version: 4, reason_code: 'QUALITY_ISSUE', description: '<script>质量问题</script>', policy_version: 'old-policy',
      eligibility_snapshot: { eligible: true, reason_codes: [], requires_human: false, policy_version: 'old-policy' } }, result: null,
    confirmation: { confirmation_id: 'return-confirmation', proposal_id: 'return-proposal', decision: 'reject', decided_at: '2026-11-15T00:00:00Z', consumed_at: null, result_ref: null } }
  const html = renderToStaticMarkup(<WorkflowProposalDetails proposal={proposal} />)
  for (const label of ['return-proposal', 'original-order', 'QUALITY_ISSUE', 'old-policy', '已拒绝', '尚未退款']) expect(html).toContain(label)
  expect(html).not.toContain('purchase-proposal')
  expect(html).not.toContain('<script>')
  expect(html).not.toContain('已提交业务回执')
})
