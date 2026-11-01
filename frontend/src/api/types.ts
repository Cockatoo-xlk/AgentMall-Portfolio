export type Category = 'keyboard' | 'mouse' | 'headphones'
export type Address = 'demo_dorm' | 'demo_home'
export type OrderStatus =
  'PENDING_PAYMENT' | 'PAID' | 'CANCELLED' | 'EXPIRED' | 'SHIPPED' | 'DELIVERED' | 'REFUNDED'
export interface User {
  user_id: string
  role: 'buyer' | 'merchant'
  store_id: string
}
export interface Product {
  id: string
  name: string
  category: Category
  attributes: Record<string, string>
  description: string
  price_cents: number
  currency: 'CNY'
  available: number
  catalog_version: number
}
export interface Page<T> {
  items: T[]
  next_cursor: string | null
}
export interface CartItem {
  product_id: string
  quantity: number
  name: string
  unit_price_cents: number
  available: number
  active: boolean
}
export interface CartDTO {
  id: string
  user_id: string
  store_id: string
  version: number
  items: CartItem[]
}
export interface SnapshotItem {
  product_id: string
  name_snapshot: string
  unit_price_cents: number
  quantity: number
  attributes_snapshot: Record<string, string>
  catalog_version?: number
}
export interface Confirmation {
  confirmation_id: string
  proposal_id: string
  decision: 'approve' | 'reject'
  decided_at: string
  consumed_at: string | null
  result_ref: string | null
}
interface ReceiptBase {
  action_id: string
  resource_id: string
  order_id: string
  total_cents: number
  currency: 'CNY'
  created_at: string
}
export type CartConsumption = 'CONSUMED' | 'SKIPPED_CART_CHANGED' | 'NOT_APPLICABLE'
export interface Receipt extends ReceiptBase {
  cart_consumption?: CartConsumption | null
  status: 'PENDING_PAYMENT'
}
export interface MockPaymentReceipt extends ReceiptBase {
  action_type: 'MOCK_PAYMENT'
  status: 'SUCCEEDED' | 'DECLINED' | 'EXPIRED'
  payment_id: string | null
  order_status: 'PAID' | 'PENDING_PAYMENT' | 'EXPIRED'
}
export interface CancelOrderReceipt extends ReceiptBase {
  action_type: 'CANCEL_ORDER'
  status: 'CANCELLED' | 'EXPIRED'
}
export interface ReturnReceipt {
  action_type: 'RETURN_REQUEST' | 'RETURN_CANCEL'
  action_id: string
  resource_id: string
  case_id: string
  order_id: string
  status: 'REQUESTED' | 'CANCELLED'
  created_at: string
}
export interface RefundReceipt {
  action_type: 'MOCK_REFUND'
  action_id: string
  resource_id: string
  refund_id: string
  case_id: string
  order_id: string
  payment_id: string
  amount_cents: number
  currency: 'CNY'
  status: 'SUCCEEDED'
  order_status: 'REFUNDED'
  created_at: string
}
export type ActionReceipt =
  | Receipt
  | MockPaymentReceipt
  | CancelOrderReceipt
  | ReturnReceipt
  | RefundReceipt
interface ProposalBase {
  server_time?: string | null
  proposal_id: string
  payload_hash: string
  schema_version: number
  expires_at: string
  status: 'PENDING' | 'APPROVED' | 'REJECTED' | 'EXECUTED' | 'EXPIRED'
  confirmation: Confirmation | null
}
export interface CheckoutProposal extends ProposalBase {
  action_type: 'CHECKOUT'
  canonical_payload: {
    cart_source?: { cart_id: string; user_id: string; store_id: string; version: number }
    items: SnapshotItem[]
    total_cents: number
    currency: 'CNY'
    address_label: Address
    policy_version: string
    schema_version: number
  }
  result: Receipt | null
}
export interface OrderActionPayload {
  schema_version: 1
  order_id: string
  expected_version: number
  total_cents: number
  currency: 'CNY'
  policy_version: 'demo-v1'
}
export interface MockPaymentProposal extends ProposalBase {
  action_type: 'MOCK_PAYMENT'
  canonical_payload: OrderActionPayload
  result: MockPaymentReceipt | null
}
export interface CancelOrderProposal extends ProposalBase {
  action_type: 'CANCEL_ORDER'
  canonical_payload: OrderActionPayload
  result: CancelOrderReceipt | null
}
export type ReturnReasonCode =
  | 'QUALITY_ISSUE'
  | 'NOT_NEEDED'
  | 'QUALITY_DISPUTE'
  | 'POLICY_DISPUTE'
  | 'INSUFFICIENT_INFORMATION'
  | 'OTHER'
export interface EligibilityResult {
  eligible: boolean
  reason_codes: string[]
  requires_human: boolean
  policy_version: string
}
export interface ReturnRequestProposal extends ProposalBase {
  action_type: 'RETURN_REQUEST'
  canonical_payload: {
    schema_version: 1
    order_id: string
    expected_order_version: number
    reason_code: ReturnReasonCode
    description: string
    policy_version: string
    eligibility_snapshot: EligibilityResult
  }
  result: ReturnReceipt | null
}
export interface ReturnCancelProposal extends ProposalBase {
  action_type: 'RETURN_CANCEL'
  canonical_payload: {
    schema_version: 1
    order_id: string
    case_id: string
    expected_version: number
    policy_version: string
  }
  result: ReturnReceipt | null
}
export interface MockRefundProposal extends ProposalBase {
  action_type: 'MOCK_REFUND'
  canonical_payload: {
    schema_version: 1
    order_id: string
    case_id: string
    payment_id: string
    expected_version: number
    expected_order_version: number
    amount_cents: number
    currency: 'CNY'
    policy_version: string
  }
  result: RefundReceipt | null
}
export type Proposal =
  | CheckoutProposal
  | MockPaymentProposal
  | CancelOrderProposal
  | ReturnRequestProposal
  | ReturnCancelProposal
  | MockRefundProposal
export interface Order {
  id: string
  user_id: string
  store_id: string
  proposal_id: string
  status: OrderStatus
  total_cents: number
  currency: 'CNY'
  address_label: Address
  expires_at: string
  created_at: string
  paid_at?: string | null
  shipped_at?: string | null
  delivered_at?: string | null
  version: number
  policy_version: string
  items: SnapshotItem[]
}
export interface AgentResponse {
  answer: string
  proposal_refs: string[]
  resource_refs: { type: 'product' | 'order'; id: string }[]
  status: 'done' | 'needs_input' | 'proposal' | 'blocked' | 'error'
}
export interface CartCheckout {
  request_id: string
  proposal_slot: 'web_cart'
  cart_id: string
  expected_cart_version: number
  address_label: Address
}
