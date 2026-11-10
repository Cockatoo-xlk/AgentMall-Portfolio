import { describe, expect, it } from 'vitest'
import { contextRunInput, freshRecommendationConstraints } from './threadContext'

describe('contextRunInput', () => {
  it('binds the displayed version and exact list to this request', () => {
    expect(contextRunInput('request-1', '就买第二款', 7, 'list-old')).toEqual({
      request_id: 'request-1', message: '就买第二款', expected_context_version: 7, candidate_set_id: 'list-old',
    })
  })
  it('does not turn preferences into purchase permission', () => {
    expect(contextRunInput('request-2', '推荐键盘', 0)).toEqual({
      request_id: 'request-2', message: '推荐键盘', expected_context_version: 0,
    })
  })
})

it('retrying recommendations keeps current server preferences instead of restoring an old Run budget', () => {
  expect(freshRecommendationConstraints({ max_price_cents: 30000, category: 'keyboard',
    noise_preference: 'quiet', product_needs: { connection: '无线' }, quantity: 2,
    address_label: 'demo_dorm', purchase_requested: true, exclude_product_ids: ['original-sku'] })).toEqual({
    purchase_requested: false, return_requested: false, support_requested: false,
    quantity: null, address_label: null, exclude_product_ids: ['original-sku'],
  })
})
