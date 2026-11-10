import { BrowserRouter, Routes, Route, Link } from 'react-router'
import { AuthProvider, useAuth } from './state/Auth'
import { CartProvider } from './state/Cart'
import BuyerOnly from './components/BuyerOnly'
import Layout from './components/Layout'
import Catalog from './pages/Catalog'
import AgentWorkspace from './pages/AgentWorkspace'
import AfterSales from './pages/AfterSales'
import ProductDetail from './pages/ProductDetail'
import Login from './pages/Login'
import Cart from './pages/Cart'
import Proposal from './pages/Proposal'
import Orders, { OrderDetail } from './pages/Orders'
import ChatPanel from './components/ChatPanel'
import MerchantWorkbench from './pages/MerchantWorkbench'
import EvaluationStudio from './pages/EvaluationStudio'
import RetrievalQuality from './pages/RetrievalQuality'
function StoreRoutes() {
  const { user } = useAuth()
  return (
    <CartProvider key={user?.user_id ?? 'guest'}>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<Catalog />} />
          <Route
            path="agent/workspace"
            element={
              <BuyerOnly>
                <AgentWorkspace />
              </BuyerOnly>
            }
          />
          <Route
            path="after-sales"
            element={
              <BuyerOnly>
                <AfterSales />
              </BuyerOnly>
            }
          />
          <Route path="login" element={<Login />} />
          <Route path="merchant" element={<MerchantWorkbench />} />
          <Route path="engineering/evals" element={<EvaluationStudio />} />
          <Route path="engineering/evals/retrieval" element={<RetrievalQuality />} />
          <Route path="products/:id" element={<ProductDetail />} />
          <Route
            path="cart"
            element={
              <BuyerOnly>
                <Cart />
              </BuyerOnly>
            }
          />
          <Route
            path="proposals/:id"
            element={
              <BuyerOnly>
                <Proposal />
              </BuyerOnly>
            }
          />
          <Route
            path="assistant"
            element={
              <BuyerOnly>
                <main className="page narrow-page">
                  <div className="page-header">
                    <div>
                      <span className="eyebrow">SHOP WITH A LITTLE HELP</span>
                      <h1>你的 AI 购物助手</h1>
                      <p className="muted">帮你找到候选，购买由你确认。</p>
                    </div>
                  </div>
                  <ChatPanel />
                </main>
              </BuyerOnly>
            }
          />
          <Route
            path="orders"
            element={
              <BuyerOnly>
                <Orders />
              </BuyerOnly>
            }
          />
          <Route
            path="orders/:id"
            element={
              <BuyerOnly>
                <OrderDetail />
              </BuyerOnly>
            }
          />
          <Route
            path="*"
            element={
              <main className="page empty-state">
                <h1>页面不存在</h1>
                <Link to="/" className="button primary">
                  返回商品目录
                </Link>
              </main>
            }
          />
        </Route>
      </Routes>
    </CartProvider>
  )
}
export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <StoreRoutes />
      </AuthProvider>
    </BrowserRouter>
  )
}
