import type { Address, Category, OrderStatus } from './types'
export function money(cents: number): string {
  return `¥${Math.floor(cents / 100).toLocaleString('zh-CN')}.${String(cents % 100).padStart(2, '0')}`
}
export function parseBudget(value: string): number | null {
  const clean = value.trim()
  if (!clean) return null
  if (!/^\d+(\.\d{1,2})?$/.test(clean)) throw new Error('预算请输入有效金额，最多两位小数')
  const [yuan, fen = ''] = clean.split('.')
  const cents = Number(yuan) * 100 + Number(fen.padEnd(2, '0'))
  if (!Number.isSafeInteger(cents) || cents > 100_000_000) throw new Error('预算超出可用范围')
  return cents
}
export const categoryLabel = (category: Category) =>
  ({ keyboard: '键盘', mouse: '鼠标', headphones: '耳机' })[category]
export const addressLabel = (address: Address) =>
  ({ demo_dorm: '演示宿舍地址', demo_home: '演示家庭地址' })[address]
const orderStatusLabels: Record<OrderStatus, string> = {
  PENDING_PAYMENT: '待支付',
  PAID: '已支付',
  CANCELLED: '已取消',
  EXPIRED: '已过期',
  SHIPPED: '已发货',
  DELIVERED: '已签收',
  REFUNDED: '已退款',
}
export const orderStatusLabel = (status: OrderStatus): string =>
  Object.hasOwn(orderStatusLabels, status) ? orderStatusLabels[status] : '未知状态'
export const formatDate = (date: string) =>
  new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(date))
