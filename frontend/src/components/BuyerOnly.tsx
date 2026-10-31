import type { ReactNode } from 'react'
import { Link, useLocation } from 'react-router'
import { LockKeyhole, Store } from 'lucide-react'
import { useAuth } from '../state/Auth'
export default function BuyerOnly({ children }: { children: ReactNode }) {
  const { user } = useAuth()
  const location = useLocation()
  if (!user)
    return (
      <section className="page empty-state">
        <LockKeyhole size={32} />
        <h1>登录后继续</h1>
        <p>登录买家账号，即可查看你的购物车、购买提案和订单。</p>
        <Link
          className="button primary"
          to="/login"
          state={{ from: location.pathname + location.search }}
        >
          去登录
        </Link>
      </section>
    )
  if (user.role !== 'buyer')
    return (
      <section className="page empty-state">
        <Store size={32} />
        <h1>当前为商家账号</h1>
        <p>购物车、购物助手与购买确认仅向买家开放。</p>
        <Link className="button secondary" to="/">
          继续浏览商品
        </Link>
      </section>
    )
  return children
}
