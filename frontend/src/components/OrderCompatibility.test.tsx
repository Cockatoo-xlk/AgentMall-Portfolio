import { beforeEach, describe, expect, it, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { AuthProvider } from '../state/Auth'
import { OrderDetail } from '../pages/Orders'
import ConfirmationCard from './ConfirmationCard'
import type { Order, OrderStatus, Proposal } from '../api/types'

const resource = vi.hoisted(() => ({ data: null as unknown }))
vi.mock('../state/useResource', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../state/useResource')>()),
  useResource: () => ({ data: resource.data, loading: false, error: null, reload: vi.fn() }),
}))

beforeEach(() => {
  resource.data = null
})

function render(element: React.ReactNode) {
  return renderToStaticMarkup(
    <MemoryRouter>
      <AuthProvider>{element}</AuthProvider>
    </MemoryRouter>,
  )
}

const order: Order = {
  id: 'order-1',
  user_id: 'buyer-1',
  store_id: 'store-1',
  proposal_id: 'checkout-1',
  status: 'PENDING_PAYMENT',
  total_cents: 19900,
  currency: 'CNY',
  address_label: 'demo_dorm',
  expires_at: '2099-01-01T00:15:00Z',
  created_at: '2099-01-01T00:00:00Z',
  version: 1,
  policy_version: 'demo-v1',
  items: [],
}

const proposalBase = {
  proposal_id: 'action-1',
  payload_hash: 'hash',
  schema_version: 1,
  expires_at: '2099-01-01T00:10:00Z',
  status: 'PENDING' as const,
  confirmation: null,
  result: null,
}
const orderPayload = {
  schema_version: 1 as const,
  order_id: 'order-1',
  expected_version: 1,
  total_cents: 19900,
  currency: 'CNY' as const,
  policy_version: 'demo-v1' as const,
}
const receiptBase = {
  action_id: 'action-1',
  resource_id: 'order-1',
  order_id: 'order-1',
  total_cents: 19900,
  currency: 'CNY' as const,
  created_at: '2099-01-01T00:00:00Z',
}

describe('order lifecycle display', () => {
  it('offers a separate mock payment action only for a pending order', () => {
    for (const status of ['PENDING_PAYMENT', 'PAID', 'CANCELLED', 'EXPIRED', 'SHIPPED', 'DELIVERED', 'REFUNDED'] as OrderStatus[]) {
      resource.data = { ...order, status }
      const html = render(<OrderDetail />)
      expect(html.includes('>模拟付款</button>')).toBe(status === 'PENDING_PAYMENT')
      expect(html).toContain('不发生真实扣款')
    }
  })
  it.each([
    ['PENDING_PAYMENT', '待支付'],
    ['PAID', '已支付'],
    ['CANCELLED', '已取消'],
    ['EXPIRED', '已过期'],
    ['SHIPPED', '已发货'],
    ['DELIVERED', '已签收'],
    ['REFUNDED', '已退款'],
  ] satisfies [OrderStatus, string][])('shows %s from the order response', (status, label) => {
    resource.data = { ...order, status }
    const html = render(<OrderDetail />)
    expect(html).toContain(`<strong>${label}</strong>`)
    expect(html).toContain(`<span class="badge">${label}</span>`)
    if (status !== 'PENDING_PAYMENT') expect(html).not.toContain('待支付')
  })

  it('does not present an unrecognized server status as pending payment', () => {
    resource.data = { ...order, status: 'FUTURE_STATUS' }
    const html = render(<OrderDetail />)
    expect(html).toContain('未知状态')
    expect(html).not.toContain('待支付')
  })
})

describe('proposal compatibility', () => {
  const aftersalesProposals = [
    {
      ...proposalBase,
      action_type: 'RETURN_REQUEST',
      canonical_payload: {
        schema_version: 1,
        order_id: 'order-1',
        expected_order_version: 4,
        reason_code: 'NOT_NEEDED',
        description: '申请退货',
        policy_version: 'demo-v1',
        eligibility_snapshot: {
          eligible: true,
          reason_codes: [],
          requires_human: false,
          policy_version: 'demo-v1',
        },
      },
    },
    {
      ...proposalBase,
      action_type: 'RETURN_CANCEL',
      canonical_payload: {
        schema_version: 1,
        order_id: 'order-1',
        case_id: 'case-1',
        expected_version: 1,
        policy_version: 'demo-v1',
      },
    },
    {
      ...proposalBase,
      action_type: 'MOCK_REFUND',
      canonical_payload: {
        schema_version: 1,
        order_id: 'order-1',
        case_id: 'case-1',
        payment_id: 'payment-1',
        expected_version: 3,
        expected_order_version: 4,
        amount_cents: 19900,
        currency: 'CNY',
        policy_version: 'demo-v1',
      },
    },
  ] as const satisfies readonly Proposal[]

  it.each([
    [aftersalesProposals[0], '售后申请提案'],
    [aftersalesProposals[1], '撤回售后申请提案'],
    [aftersalesProposals[2], '模拟退款提案'],
  ] as const)('renders $1 as its own read-only action', (proposal, title) => {
    resource.data = proposal
    for (const compact of [false, true]) {
      const html = render(<ConfirmationCard proposalId="action-1" compact={compact} />)
      expect(html).toContain(`<h2>${title}</h2>`)
      expect(html).toContain('只读提案')
      expect(html).toContain('href="/orders/order-1"')
      expect(html).not.toContain('取消订单提案')
      expect(html).not.toContain('NaN')
      expect(html).not.toContain('确认并创建订单')
      expect(html).not.toContain('继续创建订单')
      expect(html).not.toContain('拒绝此提案')
      expect(html).not.toContain('查看并确认提案')
      if (proposal.action_type === 'MOCK_REFUND') {
        expect(html).toContain('退款金额')
        expect(html).toContain('¥199.00')
      } else {
        expect(html).not.toContain('订单金额')
      }
    }
  })

  it.each([
    [aftersalesProposals[0], 'RETURN_REQUEST', 'REQUESTED', '售后申请已提交'],
    [aftersalesProposals[1], 'RETURN_CANCEL', 'CANCELLED', '售后申请已撤回'],
  ] as const)('shows $1 receipts as case state, not order state', (proposal, action_type, status, label) => {
    resource.data = {
      ...proposal,
      status: 'EXECUTED',
      result: {
        action_type,
        action_id: 'action-1',
        resource_id: 'case-1',
        case_id: 'case-1',
        order_id: 'order-1',
        status,
        created_at: '2099-01-01T00:00:00Z',
      },
    } satisfies Proposal
    const html = render(<ConfirmationCard proposalId="action-1" />)
    expect(html).toContain(`<span class="badge">${label}</span>`)
    expect(html).toContain('售后单编号')
    expect(html).toContain('case-1')
    expect(html).toContain('href="/orders/order-1"')
    expect(html).not.toContain('回执时订单状态')
    expect(html).not.toContain('已取消')
    expect(html).not.toContain('未知状态')
    expect(html).not.toContain('NaN')
  })

  it('shows the refund receipt and refunded order without checkout controls', () => {
    resource.data = {
      ...aftersalesProposals[2],
      status: 'EXECUTED',
      result: {
        action_type: 'MOCK_REFUND',
        action_id: 'action-1',
        resource_id: 'refund-1',
        refund_id: 'refund-1',
        case_id: 'case-1',
        order_id: 'order-1',
        payment_id: 'payment-1',
        amount_cents: 19900,
        currency: 'CNY',
        status: 'SUCCEEDED',
        order_status: 'REFUNDED',
        created_at: '2099-01-01T00:00:00Z',
      },
    } satisfies Proposal
    const html = render(<ConfirmationCard proposalId="action-1" compact />)
    expect(html).toContain('<span class="badge">模拟退款成功</span>')
    expect(html).toContain('退款编号')
    expect(html).toContain('refund-1')
    expect(html).toContain('case-1')
    expect(html).toContain('退款金额')
    expect(html).toContain('¥199.00')
    expect(html).toContain('回执时订单状态')
    expect(html).toContain('已退款')
    expect(html).toContain('href="/orders/order-1"')
    expect(html).not.toContain('查看并确认提案')
    expect(html).not.toContain('确认并创建订单')
  })

  it.each(['MOCK_PAYMENT', 'CANCEL_ORDER'] as const)(
    'renders %s as read-only order information without checkout controls',
    (action_type) => {
      resource.data = {
        ...proposalBase,
        action_type,
        canonical_payload: orderPayload,
      } satisfies Proposal
      let html = ''
      expect(() => {
        html = render(<ConfirmationCard proposalId="action-1" />)
      }).not.toThrow()
      expect(html).toContain('order-1')
      expect(html).toContain('¥199.00')
      expect(html).toContain('受控 API')
      expect(html).toContain('href="/orders/order-1"')
      expect(html).not.toContain('确认并创建订单')
      expect(html).not.toContain('继续创建订单')
      expect(html).not.toContain('拒绝此提案')
    },
  )

  it('keeps checkout confirmation available with the original payload', () => {
    resource.data = {
      ...proposalBase,
      action_type: 'CHECKOUT',
      canonical_payload: {
        items: [],
        total_cents: 19900,
        currency: 'CNY',
        address_label: 'demo_dorm',
        policy_version: 'demo-v1',
        schema_version: 1,
      },
    } satisfies Proposal
    expect(render(<ConfirmationCard proposalId="action-1" />)).toContain('确认并创建订单')
  })

  it.each([
    ['SUCCEEDED', 'PAID', '模拟支付成功'],
    ['DECLINED', 'PENDING_PAYMENT', '模拟支付已拒付'],
    ['EXPIRED', 'EXPIRED', '订单已过期'],
  ] as const)(
    'shows a %s payment receipt without offering checkout',
    (status, order_status, label) => {
      resource.data = {
        ...proposalBase,
        status: 'EXECUTED',
        action_type: 'MOCK_PAYMENT',
        canonical_payload: orderPayload,
        result: {
          ...receiptBase,
          action_type: 'MOCK_PAYMENT',
          status,
          order_status,
          payment_id: status === 'SUCCEEDED' ? 'payment-1' : null,
        },
      } satisfies Proposal
      const html = render(<ConfirmationCard proposalId="action-1" compact />)
      expect(html).toContain(label)
      expect(html).toContain('href="/orders/order-1"')
      expect(html).not.toContain('查看并确认提案')
    },
  )

  it.each([
    ['CANCELLED', '已取消'],
    ['EXPIRED', '已过期'],
  ] as const)('shows a %s cancellation receipt', (status, label) => {
    resource.data = {
      ...proposalBase,
      status: 'EXECUTED',
      action_type: 'CANCEL_ORDER',
      canonical_payload: orderPayload,
      result: { ...receiptBase, action_type: 'CANCEL_ORDER', status },
    } satisfies Proposal
    expect(render(<ConfirmationCard proposalId="action-1" />)).toContain(label)
  })

  it('does not describe the historical checkout receipt as the current order status', () => {
    resource.data = {
      ...proposalBase,
      status: 'EXECUTED',
      action_type: 'CHECKOUT',
      canonical_payload: {
        items: [],
        total_cents: 19900,
        currency: 'CNY',
        address_label: 'demo_dorm',
        policy_version: 'demo-v1',
        schema_version: 1,
      },
      result: { ...receiptBase, status: 'PENDING_PAYMENT' },
    } satisfies Proposal
    const html = render(<ConfirmationCard proposalId="action-1" />)
    expect(html).toContain('查看订单')
    expect(html).not.toContain('<span class="badge">待支付</span>')
  })
})
