import { ApiClient, ApiError } from './client'
import type { Proposal, Order, Confirmation, Receipt } from './types'

export async function readOutcome(
  client: ApiClient,
  id: string,
): Promise<{ proposal: Proposal; order: Order | null }> {
  const proposal = await client.get<Proposal>(`/proposals/${encodeURIComponent(id)}`)
  const order = proposal.result
    ? await client.get<Order>(`/orders/${proposal.result.order_id}`)
    : null
  return { proposal, order }
}
export async function confirmAndExecute(client: ApiClient, id: string): Promise<Order> {
  const path = `/proposals/${encodeURIComponent(id)}`
  const initial = await readOutcome(client, id)
  if (initial.order) return initial.order
  if (['EXPIRED', 'REJECTED'].includes(initial.proposal.status))
    throw new ApiError(409, 'STALE_PROPOSAL')
  try {
    const confirmation =
      initial.proposal.confirmation ??
      (await client.post<Confirmation>(`${path}/confirmations`, { decision: 'approve' }))
    if (confirmation.decision === 'reject') throw new ApiError(409, 'REJECTED')
    const receipt = await client.post<Receipt>(
      '/orders',
      { proposal_id: id, confirmation_id: confirmation.confirmation_id },
      `web:order:${id}`,
    )
    return await client.get<Order>(`/orders/${receipt.order_id}`)
  } catch (error) {
    // A lost response can follow a successful commit. Only reads run in this recovery branch.
    try {
      const recovered = await readOutcome(client, id)
      if (recovered.order) return recovered.order
    } catch {
      /* Keep the unknown state. */
    }
    if (error instanceof ApiError && !error.ambiguous) throw error
    throw new ApiError(0, 'OUTCOME_UNKNOWN', true)
  }
}
