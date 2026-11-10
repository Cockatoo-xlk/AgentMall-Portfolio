import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { createElement } from 'react'
import { categoryLabels, productSpecs, attributeValue } from './catalog'
import type { Category, Product } from './types'
import ProductArt from '../components/ProductArt'

const base = { id: 'synthetic', name: '测试合成商品', description: '合成目录', price_cents: 299900, currency: 'CNY', available: 12, catalog_version: 1 } as const

describe('expanded category presentation', () => {
  it('has thirteen labelled and independently illustrated categories', () => {
    expect(Object.keys(categoryLabels)).toHaveLength(13)
    const images = new Set<string>()
    for (const category of Object.keys(categoryLabels) as Category[]) {
      const svg = renderToStaticMarkup(createElement(ProductArt, { category }))
      expect(svg).toContain('<svg')
      expect(svg).not.toContain('<image')
      expect(svg).not.toContain('http')
      images.add(svg.replace(/_R_[^"-]+/g, 'id'))
    }
    expect(images.size).toBe(13)
  })
  it('shows category-specific facts without inventing keyboard attributes', () => {
    const phone: Product = { ...base, category: 'smartphone', attributes: { memory: '8GB', storage: '256GB', screen_size: '6.5英寸', switch: 'not applicable' } }
    expect(productSpecs(phone)).toEqual(['8GB', '256GB', '6.5英寸'])
    expect(productSpecs({ ...base, category: 'monitor', attributes: { screen_size: '27英寸', resolution: '2560×1440', refresh_rate: '100Hz' } })).toEqual(['27英寸', '2560×1440', '100Hz'])
    expect(attributeValue(['wired', 'wireless'])).toBe('有线 / 无线')
  })
})
