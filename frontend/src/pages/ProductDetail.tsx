import { useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router'
import { ArrowLeft, ArrowRight, Check, Minus, Plus, ShoppingBag, Sparkles } from 'lucide-react'
import type { Product } from '../api/types'
import { categoryLabel, money } from '../api/format'
import { errorMessage } from '../api/client'
import { useAuth } from '../state/Auth'
import { useCart } from '../state/Cart'
import { useMounted } from '../state/useResource'
import ProductArt from '../components/ProductArt'

const attributeLabels: Record<string, string> = {
  switch: '轴体',
  connection: '连接方式',
  size: '规格',
  noise: '噪声标签',
}

export default function ProductDetail() {
  const params = useParams<{ id: string; productId: string }>()
  const id = params.id ?? params.productId
  const { client, user } = useAuth()
  const { cart, busy, setQuantity } = useCart()
  const [product, setProduct] = useState<Product | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [writeError, setWriteError] = useState<string | null>(null)
  const [quantity, setCount] = useState(1)
  const [pending, setPending] = useState(false)
  const [retry, setRetry] = useState(0)
  const lock = useRef(false)
  const alive = useMounted()
  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    setProduct(null)
    setError(null)
    setCount(1)
    setWriteError(null)
    client
      .get<Product>(`/products/${encodeURIComponent(id ?? '')}`, controller.signal)
      .then((value) => {
        if (!controller.signal.aborted) setProduct(value)
      })
      .catch((err) => {
        if (!controller.signal.aborted) setError(errorMessage(err))
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false)
      })
    return () => controller.abort()
  }, [client, id, retry])
  const inCart = cart?.items.find((item) => item.product_id === product?.id)?.quantity ?? 0
  const maxQuantity = Math.max(0, Math.min(product?.available ?? 0, 10) - inCart)
  const merchant = user?.role === 'merchant'
  async function add() {
    if (
      !cart ||
      !product ||
      user?.role !== 'buyer' ||
      busy ||
      lock.current ||
      quantity > maxQuantity
    )
      return
    lock.current = true
    setPending(true)
    setWriteError(null)
    try {
      await setQuantity(product.id, inCart + quantity)
    } catch (err) {
      if (alive.current) setWriteError(errorMessage(err))
    } finally {
      lock.current = false
      if (alive.current) setPending(false)
    }
  }
  return (
    <main className="page detail-page">
      <Link className="back-link" to="/">
        <ArrowLeft size={16} />
        返回全部商品
      </Link>
      {loading ? (
        <div className="loading" role="status">
          <span className="spinner" />
          正在读取商品详情…
        </div>
      ) : error || !product ? (
        <div className="empty-state" role="alert">
          <ShoppingBag size={32} />
          <h1>暂时无法载入这件商品</h1>
          <p className="muted">{error ?? '这件商品可能已不在目录中。'}</p>
          <button className="button secondary" onClick={() => setRetry((value) => value + 1)}>
            重新加载
          </button>
        </div>
      ) : (
        <>
          <div className="product-detail-grid">
            <div className={`detail-art-panel product-image-${product.category}`}>
              <span className="badge detail-art-badge">
                {categoryLabel(product.category)} · 合成商品
              </span>
              <ProductArt category={product.category} variant={product.id} />
              <div className="detail-art-caption">
                原创合成示意图<span>外观仅作展示，以商品参数为准</span>
              </div>
            </div>
            <section className="detail-content">
              <span className="eyebrow">DESK ESSENTIALS / {categoryLabel(product.category)}</span>
              <h1>{product.name}</h1>
              <p className="detail-description">{product.description}</p>
              <div className="detail-price-row">
                <span className="price">{money(product.price_cents)}</span>
                <span className="product-stock">
                  <span className={product.available > 0 ? 'stock-dot' : 'stock-dot out'} />
                  {product.available > 0 ? `当前库存 ${product.available} 件` : '暂无库存'}
                </span>
              </div>
              <div className="detail-attributes">
                <h2>商品参数</h2>
                <dl>
                  {Object.entries(product.attributes).map(([key, value]) => (
                    <div key={key}>
                      <dt>{attributeLabels[key] ?? key}</dt>
                      <dd>{String(value)}</dd>
                    </div>
                  ))}
                </dl>
              </div>
              {inCart > 0 && (
                <p className="in-cart-note">
                  <Check size={15} />
                  购物车中已有 {inCart} 件
                  <Link to="/cart">
                    查看购物车
                    <ArrowRight size={13} />
                  </Link>
                </p>
              )}
              <div className="detail-purchase">
                <div className="quantity-control" aria-label="购买数量">
                  <button
                    className="icon-button"
                    aria-label="减少数量"
                    disabled={quantity <= 1 || busy || merchant}
                    onClick={() => setCount((value) => Math.max(1, value - 1))}
                  >
                    <Minus size={15} />
                  </button>
                  <output aria-live="polite">{quantity}</output>
                  <button
                    className="icon-button"
                    aria-label="增加数量"
                    disabled={quantity >= maxQuantity || busy || merchant}
                    onClick={() => setCount((value) => value + 1)}
                  >
                    <Plus size={15} />
                  </button>
                </div>
                {!user ? (
                  <Link className="button primary" to="/login">
                    <ShoppingBag size={18} />
                    登录后加入购物车
                  </Link>
                ) : (
                  <button
                    className="button primary"
                    onClick={add}
                    disabled={!cart || busy || pending || quantity > maxQuantity || merchant}
                  >
                    <ShoppingBag size={18} />
                    {pending
                      ? '正在加入'
                      : merchant
                        ? '商家账户不可加购'
                        : maxQuantity < 1
                          ? '库存已达上限'
                          : '加入购物车'}
                  </button>
                )}
              </div>
              {writeError && (
                <p className="notice error" role="alert">
                  {writeError}
                </p>
              )}
              <p className="purchase-note">
                每款最多 10 件。加入购物车不会预留库存，下单前请核对确认信息。
              </p>
              {user?.role !== 'merchant' && (
                <Link className="detail-assistant" to="/assistant">
                  <Sparkles size={19} />
                  <span>
                    想知道它是否适合你？<small>告诉 AI 你的使用场景和预算</small>
                  </span>
                  <ArrowRight size={18} />
                </Link>
              )}
            </section>
          </div>
          <div className="detail-disclosure">
            <div>
              <span className="eyebrow">ABOUT THIS PRODUCT</span>
              <h2>认真选购，从了解开始。</h2>
            </div>
            <p>
              这是自建的合成演示商品，不对应真实品牌。噪声标签为定性描述，不代表绝对无声。页面所示价格、库存与参数来自商品目录，交易为模拟演示。
            </p>
          </div>
        </>
      )}
    </main>
  )
}
