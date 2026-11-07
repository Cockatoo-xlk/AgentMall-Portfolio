import type { Category } from "./types"
export function contextRunInput(request_id: string, message: string, version: number, candidateSetId?: string, bundleId?: string) {
  return { request_id, message, expected_context_version: version,
    ...(candidateSetId ? { candidate_set_id: candidateSetId } : {}),
    ...(bundleId ? { bundle_id: bundleId } : {}) }
}
export interface CandidateItem {
  rank: number
  id: string
  name: string
  price_cents: number
  currency: string
  catalog_version: number
}
export interface BundleOffer {
  bundle_id: string; name: string; thread_id: string; source_run_id: string; context_version: number
  items: (CandidateItem & { category: Category; attributes: Record<string, string>; quantity: number; quantity_source: string; subtotal_cents: number; available_snapshot: number; reasons: string[] })[]
  budget_cents: number; total_cents: number; remaining_cents: number; expires_at: string; valid: boolean; invalid_reason: string | null
}
export interface ThreadContext {
  bundles?: BundleOffer[]
  bundle_status?: { status: string; reason?: string; missing_categories?: Category[] }
  version: number
  preferences: { bundle?: { budget_cents: number; parts: { category: Category }[] }; category?: string; max_price_cents?: number; noise_preference?: string;
    product_needs?: { connection?: string; layout?: string; keyboard_type?: string; usage?: string; screen_inches?: string; activity?: string; product_kind?: string; excluded_connections?: string[] } }
  provenance: { type?: string; run_id?: string; request_id?: string }
  updated_at: string | null
  candidate_sets: { id: string; run_id: string; valid: boolean; items: CandidateItem[] }[]
}
export interface ContextOperation { op: 'SET' | 'REPLACE' | 'CLEAR'; field: string; value?: string | number | string[] }

/** A read-only retry must use this Thread's current preferences, not an old Run's limits. */
export function freshRecommendationConstraints(previous: Record<string, unknown>) {
  const remembered = new Set(['max_price_cents', 'category', 'noise_preference', 'product_needs', 'quantity', 'address_label'])
  return { ...Object.fromEntries(Object.entries(previous).filter(([key]) => !remembered.has(key))),
    purchase_requested: false, return_requested: false, support_requested: false,
    quantity: null, address_label: null }
}
