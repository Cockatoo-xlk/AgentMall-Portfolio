import { createContext, useContext, useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { ApiError, errorMessage } from '../api/client'
import type { CartDTO } from '../api/types'
import { useAuth } from './Auth'
import { readCheckoutCart } from '../api/checkoutCart'
import { CartReadTracker } from './CartReadTracker'
interface CartValue {
  cart: CartDTO | null
  busy: boolean
  notice: string | null
  error: string | null
  refresh: () => Promise<void>
  refreshAfterCheckout: (proposalId: string) => Promise<void>
  setQuantity: (id: string, quantity: number) => Promise<void>
}
const Context = createContext<CartValue | null>(null)
export function CartProvider({ children }: { children: ReactNode }) {
  const { client, user } = useAuth()
  const [cart, setCart] = useState<CartDTO | null>(null)
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const current = useRef<CartDTO | null>(null)
  const writing = useRef(false)
  const generation = useRef(0)
  const reads = useRef(new CartReadTracker())
  function apply(next: CartDTO, read?: number) {
    const accepted =
      read === undefined ? reads.current.acceptWrite(next) : reads.current.accept(read, next)
    if (!accepted) return false
    current.current = next
    setCart(next)
    return true
  }
  useEffect(() => {
    const gen = ++generation.current
    const controller = new AbortController()
    reads.current.reset()
    const read = reads.current.begin()
    current.current = null
    setCart(null)
    setError(null)
    setNotice(null)
    if (user?.role === 'buyer')
      client
        .get<CartDTO>('/cart', controller.signal)
        .then((next) => {
          if (gen === generation.current) apply(next, read)
        })
        .catch((err) => {
          if (!controller.signal.aborted && gen === generation.current && reads.current.fail(read))
            setError(errorMessage(err))
        })
    return () => {
      generation.current = gen + 1
      controller.abort()
    }
  }, [client, user])
  async function refresh() {
    const gen = generation.current
    if (user?.role !== 'buyer') return
    const read = reads.current.begin()
    try {
      const next = await client.get<CartDTO>('/cart')
      if (gen === generation.current && apply(next, read)) {
        setError(null)
        setNotice('已核对购物车最新状态，请确认数量后再操作。')
      }
    } catch (err) {
      if (gen === generation.current && reads.current.fail(read)) setError(errorMessage(err))
    }
  }
  async function refreshAfterCheckout(proposalId: string) {
    const gen = generation.current
    if (user?.role !== 'buyer') return
    const read = reads.current.begin()
    const result = await readCheckoutCart(client, proposalId)
    if (gen !== generation.current || !reads.current.current(read)) return
    if (!result.cart) {
      reads.current.fail(read)
      current.current = null
      setCart(null)
      setNotice(null)
      setError('订单已创建，但购物车最新状态尚未核对。请先重新查询购物车；不要重复下单。')
      return
    }
    if (!apply(result.cart, read)) return
    setError(null)
    if (result.error) {
      setNotice('订单已创建，已读取最新购物车；购物车处理回执尚未核对，请检查保留的商品。')
    } else {
      const messages = {
        CONSUMED: '订单已创建，本次结算商品已从购物车移除；当前显示服务端最新购物车。',
        SKIPPED_CART_CHANGED:
          '订单已创建，但购物车在提案后已变化；已保留新增或修改的商品，请核对当前购物车。',
        NOT_APPLICABLE: '订单已创建；本提案未绑定可消费的购物车快照，购物车未被消费。',
      }
      setNotice(
        result.consumption
          ? messages[result.consumption]
          : '订单已创建，已核对最新购物车；历史回执未记录自动移除结果，请核对。',
      )
    }
  }
  async function setQuantity(id: string, quantity: number) {
    if (writing.current || user?.role !== 'buyer') return
    if (!current.current) {
      await refresh()
      return
    }
    writing.current = true
    reads.current.begin()
    setBusy(true)
    setNotice(null)
    setError(null)
    const gen = generation.current
    try {
      const data = { quantity, expected_version: current.current.version }
      const next =
        quantity === 0
          ? await client.delete<CartDTO>(`/cart/items/${id}`, {
              expected_version: data.expected_version,
            })
          : await client.put<CartDTO>(`/cart/items/${id}`, data)
      if (gen === generation.current && apply(next)) {
        setNotice(quantity === 0 ? '商品已从购物车移除。' : '购物车已更新。')
      }
    } catch (err) {
      if (gen !== generation.current) return
      if (err instanceof ApiError && (err.status === 409 || err.ambiguous)) {
        const read = reads.current.begin()
        try {
          const latest = await client.get<CartDTO>('/cart')
          if (gen === generation.current && apply(latest, read)) {
            setNotice(
              err.status === 409
                ? '购物车版本已变化，已停止本次修改并核对最新状态。请确认后再操作。'
                : '响应未收到，已核对购物车最新状态。请检查当前数量后再操作。',
            )
          }
        } catch {
          if (gen === generation.current && reads.current.fail(read)) {
            current.current = null
            setCart(null)
            setError('购物车状态待核对。查询尚未成功，请先核对购物车，再继续修改或结算。')
          }
        }
      } else setError(errorMessage(err))
    } finally {
      writing.current = false
      if (gen === generation.current) setBusy(false)
    }
  }
  return (
    <Context.Provider
      value={{ cart, busy, notice, error, refresh, refreshAfterCheckout, setQuantity }}
    >
      {children}
    </Context.Provider>
  )
}
export function useCart() {
  const value = useContext(Context)
  if (!value) throw new Error('CartProvider missing')
  return value
}
