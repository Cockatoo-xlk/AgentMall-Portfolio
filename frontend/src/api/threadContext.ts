export function contextRunInput(request_id: string, message: string, version: number, candidateSetId?: string) {
  return { request_id, message, expected_context_version: version,
    ...(candidateSetId ? { candidate_set_id: candidateSetId } : {}) }
}
export interface CandidateItem {
  rank: number
  id: string
  name: string
  price_cents: number
  currency: string
  catalog_version: number
}
export interface ThreadContext {
  version: number
  preferences: { category?: string; max_price_cents?: number; noise_preference?: string; product_needs?: Record<string, string> }
  provenance: { type?: string; run_id?: string; request_id?: string }
  updated_at: string | null
  candidate_sets: { id: string; run_id: string; valid: boolean; items: CandidateItem[] }[]
}
export interface ContextOperation { op: 'SET' | 'REPLACE' | 'CLEAR'; field: string; value?: string | number }

/** A read-only retry must use this Thread's current preferences, not an old Run's limits. */
export function freshRecommendationConstraints(previous: Record<string, unknown>) {
  const remembered = new Set(['max_price_cents', 'category', 'noise_preference', 'product_needs', 'quantity', 'address_label'])
  return { ...Object.fromEntries(Object.entries(previous).filter(([key]) => !remembered.has(key))),
    purchase_requested: false, return_requested: false, support_requested: false,
    quantity: null, address_label: null }
}
