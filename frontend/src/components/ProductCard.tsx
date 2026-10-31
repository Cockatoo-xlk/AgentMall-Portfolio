import { useRef, useState } from 'react'
import { Link } from 'react-router'
import { ArrowUpRight, Plus } from 'lucide-react'
import type { Product } from '../api/types'
import { categoryLabel, money } from '../api/format'
import { errorMessage } from '../api/client'
import { useAuth } from '../state/Auth'
import { useCart } from '../state/Cart'
import { useMounted } from '../state/useResource'
import ProductArt from './ProductArt'

export default function ProductCard({ product }: { product: Product }) {
  const { user } = useAuth()
  const { cart, busy, setQuantity } = useCart()
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const lock = useRef(false)
  const alive = useMounted()
  const quantity = cart?.items.find((item) => item.product_id === product.id)?.quantity ?? 0
  const merchant = user?.role === 'merchant'
  const unavailable = product.available <= quantity || quantity >= 10
  const unavailableLabel = product.available <= quantity ? '库存已达上限' : '已达数量上限'
  const attributes = ['switch', 'connection', 'size']
    .map((key) => product.attributes[key])
    .filter((value) => value && value !== '无')
  async function add() {
    if (!cart || lock.current || busy || unavailable || user?.role !== 'buyer') return
    lock.current = true
    setPending(true)
    setError(null)
    try {
      await setQuantity(product.id, quantity + 1)
    } catch (err) {
      if (alive.current) setError(errorMessage(err))
    } finally {
      lock.current = false
      if (alive.current) setPending(false)
    }
  }
  return (
    <article className="product-card" data-testid="product-card">
      <Link
        className={`product-image product-image-${product.category}`}
        to={`/products/${product.id}`}
        aria-label={`查看${product.name}`}
        tabIndex={-1}
      >
        <ProductArt category={product.category} variant={product.id} />
        <span className="art-caption">合成示意图</span>
        <span className="product-image-arrow">
          <ArrowUpRight size={17} />
        </span>
      </Link>
      <div className="product-card-body">
        <span className="product-category">{categoryLabel(product.category)}</span>
        <h3>
          <Link to={`/products/${product.id}`}>{product.name}</Link>
        </h3>
        <p className="product-specs">{attributes.join(' · ') || '查看商品详细参数'}</p>
        <div className="product-stock">
          <span className={product.available > 0 ? 'stock-dot' : 'stock-dot out'} />
          {product.available > 0 ? `库存 ${product.available} 件` : '暂无库存'}
          {quantity > 0 && <span className="cart-quantity-hint">购物车 {quantity} 件</span>}
        </div>
        <div className="product-card-bottom">
          <span className="price">{money(product.price_cents)}</span>
          {!user ? (
            <Link className="button card-add secondary" to="/login">
              登录后加入购物车
            </Link>
          ) : (
            <button
              className="button card-add secondary"
              disabled={!cart || busy || pending || unavailable || merchant}
              onClick={add}
              title={merchant ? '商家账户不能操作买家购物车' : undefined}
            >
              <Plus size={15} />
              {pending
                ? '正在加入'
                : merchant
                  ? '仅买家可加购'
                  : unavailable
                    ? unavailableLabel
                    : '加入购物车'}
            </button>
          )}
        </div>
        {error && (
          <p className="notice error compact" role="alert">
            {error}
          </p>
        )}
      </div>
    </article>
  )
}
