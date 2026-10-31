import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { Link } from 'react-router'
import {
  ArrowDown,
  ArrowRight,
  Headphones,
  Keyboard,
  Layers2,
  Mouse,
  Search,
  SlidersHorizontal,
  Sparkles,
} from 'lucide-react'
import type { Category, Page, Product } from '../api/types'
import { errorMessage } from '../api/client'
import { parseBudget } from '../api/format'
import { useAuth } from '../state/Auth'
import ProductArt from '../components/ProductArt'
import ProductCard from '../components/ProductCard'

interface Filters {
  query: string
  category: Category | ''
  budget: number | null
}
const categories = [
  { value: '', label: '全部商品', icon: Layers2 },
  { value: 'keyboard', label: '键盘', icon: Keyboard },
  { value: 'mouse', label: '鼠标', icon: Mouse },
  { value: 'headphones', label: '耳机', icon: Headphones },
] as const

export default function Catalog() {
  const { client, user } = useAuth()
  const [query, setQuery] = useState('')
  const [budget, setBudget] = useState('')
  const [filters, setFilters] = useState<Filters>({ query: '', category: '', budget: null })
  const [products, setProducts] = useState<Product[]>([])
  const [nextCursor, setNextCursor] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadingMore, setLoadingMore] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [moreError, setMoreError] = useState<string | null>(null)
  const [inputError, setInputError] = useState<string | null>(null)
  const [retry, setRetry] = useState(0)
  const generation = useRef(0)
  const moreRequest = useRef<AbortController | null>(null)
  const moreLock = useRef(false)
  const params = new URLSearchParams({ limit: '8' })
  if (filters.query) params.set('query', filters.query)
  if (filters.category) params.set('category', filters.category)
  if (filters.budget !== null) params.set('max_price_cents', String(filters.budget))
  const queryString = params.toString()
  useEffect(() => {
    const current = ++generation.current
    const controller = new AbortController()
    moreRequest.current?.abort()
    moreLock.current = false
    setLoading(true)
    setLoadingMore(false)
    setError(null)
    setMoreError(null)
    setProducts([])
    setNextCursor(null)
    client
      .get<Page<Product>>(`/products?${queryString}`, controller.signal)
      .then((page) => {
        if (controller.signal.aborted || current !== generation.current) return
        setProducts(page.items)
        setNextCursor(page.next_cursor)
      })
      .catch((err) => {
        if (!controller.signal.aborted && current === generation.current)
          setError(errorMessage(err))
      })
      .finally(() => {
        if (!controller.signal.aborted && current === generation.current) setLoading(false)
      })
    return () => {
      controller.abort()
      moreRequest.current?.abort()
      generation.current = current + 1
    }
  }, [client, queryString, retry])
  async function loadMore() {
    if (!nextCursor || loading || moreLock.current) return
    const current = generation.current
    const controller = new AbortController()
    moreRequest.current = controller
    moreLock.current = true
    setLoadingMore(true)
    setMoreError(null)
    const nextParams = new URLSearchParams(queryString)
    nextParams.set('cursor', nextCursor)
    try {
      const page = await client.get<Page<Product>>(`/products?${nextParams}`, controller.signal)
      if (controller.signal.aborted || current !== generation.current) return
      setProducts((previous) => [
        ...previous,
        ...page.items.filter((item) => !previous.some((existing) => existing.id === item.id)),
      ])
      setNextCursor(page.next_cursor)
    } catch (err) {
      if (!controller.signal.aborted && current === generation.current)
        setMoreError(errorMessage(err))
    } finally {
      if (!controller.signal.aborted && current === generation.current) {
        moreLock.current = false
        setLoadingMore(false)
      }
    }
  }
  function applyFilters(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    try {
      const cents = parseBudget(budget)
      setInputError(null)
      setFilters((current) => ({ ...current, query: query.trim(), budget: cents }))
    } catch (err) {
      setInputError(errorMessage(err))
    }
  }
  function reset() {
    setQuery('')
    setBudget('')
    setInputError(null)
    setFilters({ query: '', category: '', budget: null })
  }
  return (
    <main className="page catalog-page">
      <section className="catalog-hero" aria-labelledby="hero-heading">
        <div className="hero-copy">
          <span className="eyebrow">
            <span className="eyebrow-dot" />
            为日常，认真挑选
          </span>
          <h1 id="hero-heading">
            为你的桌面，
            <br />
            找到刚刚好<span>。</span>
          </h1>
          <p>
            从一把顺手的键盘，到一副陪伴专注的耳机。
            <br className="desktop-break" />
            按你的需要，发现属于自己的桌面好物。
          </p>
          <div className="hero-actions">
            <a className="button primary" href="#catalog">
              开始挑选
              <ArrowDown size={16} />
            </a>
            {user?.role !== 'merchant' && (
              <Link className="hero-assistant-link" to="/assistant">
                <Sparkles size={17} />让 AI 帮我选
                <ArrowRight size={15} />
              </Link>
            )}
          </div>
          <div className="hero-note">
            <span />
            合成商品展示 · 按需筛选 · 自主确认
          </div>
        </div>
        <div className="hero-visual">
          <div className="hero-orbit orbit-one" />
          <div className="hero-orbit orbit-two" />
          <span className="hero-art-label">
            DESK ESSENTIALS<span>让桌面，留一点喜欢。</span>
          </span>
          <ProductArt category="keyboard" variant="hero" />
          <span className="hero-swatch">
            <i />
            <i />
            <i />
            <span>简单一点，恰到好处</span>
          </span>
          <span className="hero-visual-caption">原创合成示意图</span>
        </div>
      </section>
      <section className="catalog-section" id="catalog" aria-labelledby="catalog-heading">
        <div className="section-heading">
          <div>
            <span className="eyebrow">THE EVERYDAY EDIT</span>
            <h2 id="catalog-heading">发现桌面好物</h2>
          </div>
          <p className="muted">选你所需，让日常更顺手。</p>
        </div>
        <div className="catalog-toolbar">
          <div className="category-tabs" aria-label="商品分类">
            {categories.map((category) => {
              const Icon = category.icon
              return (
                <button
                  key={category.value}
                  className={
                    filters.category === category.value ? 'category-tab active' : 'category-tab'
                  }
                  aria-pressed={filters.category === category.value}
                  onClick={() =>
                    setFilters((current) => ({ ...current, category: category.value }))
                  }
                >
                  <Icon size={17} />
                  {category.label}
                </button>
              )
            })}
          </div>
          <span className="catalog-count" aria-live="polite">
            {loading ? '正在查找好物' : `已展示 ${products.length} 件商品`}
          </span>
        </div>
        <form className="catalog-filters" onSubmit={applyFilters}>
          <div className="catalog-search">
            <Search size={18} />
            <label className="sr-only" htmlFor="product-query">
              搜索商品
            </label>
            <input
              id="product-query"
              type="search"
              placeholder="搜索商品名称或描述"
              value={query}
              maxLength={500}
              onChange={(event) => setQuery(event.target.value)}
            />
          </div>
          <div className="budget-field">
            <label htmlFor="product-budget">最高预算（元）</label>
            <span>¥</span>
            <input
              id="product-budget"
              inputMode="decimal"
              placeholder="不限"
              value={budget}
              onChange={(event) => setBudget(event.target.value)}
              aria-invalid={!!inputError}
              aria-describedby={inputError ? 'budget-error' : undefined}
            />
          </div>
          <button className="button primary filter-button" type="submit">
            <SlidersHorizontal size={16} />
            筛选商品
          </button>
          {(filters.query || filters.budget !== null || filters.category) && (
            <button type="button" className="reset-filter" onClick={reset}>
              重置
            </button>
          )}
        </form>
        {inputError && (
          <div className="notice error" id="budget-error" role="alert">
            {inputError}
          </div>
        )}
        {loading ? (
          <div className="loading" role="status">
            <span className="spinner" />
            正在寻找桌面好物…
          </div>
        ) : error ? (
          <div className="empty-state" role="alert">
            <Search size={32} />
            <h3>商品暂时未能加载</h3>
            <p className="muted">{error}</p>
            <button className="button secondary" onClick={() => setRetry((value) => value + 1)}>
              重试加载商品
            </button>
          </div>
        ) : products.length === 0 ? (
          <div className="empty-state">
            <Search size={32} />
            <h3>暂时没有符合条件的商品</h3>
            <p className="muted">试试调整关键词、品类或预算。</p>
            <button className="button secondary" onClick={reset}>
              清除筛选
            </button>
          </div>
        ) : (
          <>
            <div className="product-grid">
              {products.map((product) => (
                <ProductCard key={product.id} product={product} />
              ))}
            </div>
            <div className="catalog-pagination">
              {moreError && (
                <p className="notice error" role="alert">
                  {moreError}
                </p>
              )}
              {nextCursor ? (
                <button
                  className="button secondary load-more"
                  disabled={loadingMore}
                  onClick={loadMore}
                >
                  {loadingMore ? (
                    <>
                      <span className="spinner" />
                      正在加载
                    </>
                  ) : (
                    <>
                      加载更多
                      <ArrowDown size={16} />
                    </>
                  )}
                </button>
              ) : (
                <p className="catalog-end">
                  <span />
                  刚刚好的选择，都在这里
                  <span />
                </p>
              )}
            </div>
          </>
        )}
      </section>
      <aside className="catalog-assistant-banner">
        <span className="assistant-banner-icon">
          <Sparkles size={24} />
        </span>
        <div>
          <h3>还没想好怎么选？</h3>
          <p>告诉 AI 你的预算和使用场景，一起缩小选择范围。</p>
        </div>
        {user?.role !== 'merchant' && (
          <Link to="/assistant" className="button secondary">
            和 AI 聊聊
            <ArrowUpRightIcon />
          </Link>
        )}
      </aside>
    </main>
  )
}

function ArrowUpRightIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <path
        d="M4 12l8-8M4 4h8v8"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}
