import { createContext, useContext, useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { ApiError, errorMessage } from '../api/client'
import type { CartDTO } from '../api/types'
import { useAuth } from './Auth'
interface CartValue {
  cart: CartDTO | null
  busy: boolean
  notice: string | null
  error: string | null
  refresh: () => Promise<void>
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
  function apply(next: CartDTO) {
    current.current = next
    setCart(next)
  }
  useEffect(() => {
    const gen = ++generation.current
    const controller = new AbortController()
    current.current = null
    setCart(null)
    setError(null)
    setNotice(null)
    if (user?.role === 'buyer')
      client
        .get<CartDTO>('/cart', controller.signal)
        .then((next) => {
          if (gen === generation.current) apply(next)
        })
        .catch((err) => {
          if (!controller.signal.aborted && gen === generation.current) setError(errorMessage(err))
        })
    return () => {
      generation.current = gen + 1
      controller.abort()
    }
  }, [client, user])
  async function refresh() {
    const gen = generation.current
    if (user?.role !== 'buyer') return
    try {
      const next = await client.get<CartDTO>('/cart')
      if (gen === generation.current) {
        apply(next)
        setError(null)
        setNotice('已核对购物车最新状态，请确认数量后再操作。')
      }
    } catch (err) {
      if (gen === generation.current) setError(errorMessage(err))
    }
  }
  async function setQuantity(id: string, quantity: number) {
    if (writing.current || user?.role !== 'buyer') return
    if (!current.current) {
      await refresh()
      return
    }
    writing.current = true
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
      if (gen === generation.current) {
        apply(next)
        setNotice(quantity === 0 ? '商品已从购物车移除。' : '购物车已更新。')
      }
    } catch (err) {
      if (gen !== generation.current) return
      if (err instanceof ApiError && (err.status === 409 || err.ambiguous)) {
        try {
          const latest = await client.get<CartDTO>('/cart')
          if (gen === generation.current) {
            apply(latest)
            setNotice(
              err.status === 409
                ? '购物车版本已变化，已停止本次修改并核对最新状态。请确认后再操作。'
                : '响应未收到，已核对购物车最新状态。请检查当前数量后再操作。',
            )
          }
        } catch {
          if (gen === generation.current) {
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
    <Context.Provider value={{ cart, busy, notice, error, refresh, setQuantity }}>
      {children}
    </Context.Provider>
  )
}
export function useCart() {
  const value = useContext(Context)
  if (!value) throw new Error('CartProvider missing')
  return value
}
