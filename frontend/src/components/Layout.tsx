import { Link, NavLink, Outlet } from 'react-router'
import {
  ArrowUpRight,
  Grid2X2,
  LogOut,
  Package,
  ShoppingBag,
  Sparkles,
  UserRound,
} from 'lucide-react'
import { useAuth } from '../state/Auth'
import { useCart } from '../state/Cart'

export default function Layout() {
  const { user, logout, expired } = useAuth()
  const { cart, notice, error } = useCart()
  const count = cart?.items.reduce((sum, item) => sum + item.quantity, 0) ?? (user?.role === 'buyer' ? '—' : 0)
  const merchant = user?.role === 'merchant'
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">
        跳转到主要内容
      </a>
      <header className="site-header">
        <div className="header-inner">
          <Link to="/" className="brand" aria-label="AgentMall 首页">
            <span className="brand-symbol">
              <ShoppingBag size={23} strokeWidth={1.7} />
              <span />
            </span>
            <span>
              Agent<span className="brand-light">Mall</span>
              <small>好物 · 刚刚好</small>
            </span>
          </Link>
          <nav className="main-nav" aria-label="主导航">
            <NavLink to="/" end>
              <Grid2X2 size={16} />
              商品
            </NavLink>
            {merchant ? (
              <span className="nav-disabled" aria-disabled="true">
                <ShoppingBag size={16} />
                购物车
              </span>
            ) : (
              <NavLink to="/cart">
                <ShoppingBag size={16} />
                购物车
                <span className="cart-count" aria-label={count === '—' ? '购物车数量待核对' : `${count} 件商品`}>
                  {count}
                </span>
              </NavLink>
            )}
            {merchant ? (
              <span className="nav-disabled" aria-disabled="true">
                <Sparkles size={16} />
                AI 助手
              </span>
            ) : (
              <NavLink to="/assistant">
                <Sparkles size={16} />
                AI 助手
              </NavLink>
            )}
            {merchant ? (
              <span className="nav-disabled" aria-disabled="true">
                <Package size={16} />
                我的订单
              </span>
            ) : (
              <NavLink to="/orders">
                <Package size={16} />
                我的订单
              </NavLink>
            )}
            {!merchant && (
              <>
                <NavLink to="/agent/workspace">工作流</NavLink>
                <NavLink to="/after-sales">售后服务</NavLink>
              </>
            )}
          </nav>
          <div className="header-account">
            {user ? (
              <>
                <span className="account-label">
                  <UserRound size={16} />
                  {merchant ? '商家账户' : '买家账户'}
                </span>
                <button
                  className="icon-button"
                  onClick={logout}
                  aria-label="退出登录"
                  title="退出登录"
                >
                  <LogOut size={17} />
                </button>
              </>
            ) : (
              <Link to="/login" className="login-link">
                <UserRound size={17} />
                登录
                <ArrowUpRight size={14} />
              </Link>
            )}
          </div>
        </div>
      </header>
      <div id="main-content" tabIndex={-1}>
        {(
          <div className="global-notice notice fixture-notice">
        合成演示数据 · 模拟资金 · 模型身份及用量以工作流服务端状态为准
          </div>
        )}
        {expired && (
          <div className="global-notice notice warning" role="alert">
            登录已过期，请重新登录后继续。<Link to="/login">重新登录</Link>
          </div>
        )}
        {notice && (
          <div className="global-notice notice" role="status">
            {notice}
          </div>
        )}
        {error && (
          <div className="global-notice notice error" role="alert">
            {error}
          </div>
        )}
        {merchant && (
          <div className="global-notice notice">
            当前为商家账户，可浏览商品；买家购物操作不可用。
          </div>
        )}
        <Outlet />
      </div>
      <footer className="site-footer">
        <div>
          <Link to="/" className="footer-brand">
            AgentMall<span className="footer-dot">.</span>
          </Link>
          <span>让每一次选择，都更合心意。</span>
        </div>
        <p>
          合成商品 · 模拟交易<span>一个 AI 购物演示空间</span>
        </p>
      </footer>
    </div>
  )
}
