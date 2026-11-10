import { ApiClient, ApiError } from './client'
import type { CartConsumption, CartDTO, Proposal } from './types'

export async function readCheckoutCart(client: ApiClient, proposalId: string) {
  let consumption: CartConsumption | null = null
  let cart: CartDTO | null = null
  let error: ApiError | null = null
  try {
    const proposal = await client.get<Proposal>(`/proposals/${encodeURIComponent(proposalId)}`)
    if (proposal.action_type !== 'CHECKOUT' || !proposal.result)
      throw new ApiError(409, 'SNAPSHOT_MISMATCH')
    consumption = proposal.result.cart_consumption ?? null
  } catch (e) {
    error = e instanceof ApiError ? e : new ApiError(0, 'NETWORK_ERROR')
  }
  // Receipt/query failure cannot justify inventing an empty cart or undoing the order.
  try {
    cart = await client.get<CartDTO>('/cart')
  } catch (e) {
    error = e instanceof ApiError ? e : new ApiError(0, 'NETWORK_ERROR')
  }
  return { cart, consumption, error }
}
