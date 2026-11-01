/** Display estimate only. Authorization always belongs to the server transaction. */
export function proposalRemaining(
  expiresAt: string,
  serverTime: string | null | undefined,
  elapsedMs: number,
): number | null {
  const zoned = /(?:Z|[+-]\d{2}:\d{2})$/
  if (
    !serverTime ||
    !zoned.test(serverTime) ||
    !zoned.test(expiresAt) ||
    !Number.isFinite(elapsedMs) ||
    elapsedMs < 0
  )
    return null
  const expiry = Date.parse(expiresAt),
    start = Date.parse(serverTime)
  if (!Number.isFinite(expiry) || !Number.isFinite(start)) return null
  return Math.max(0, Math.ceil((expiry - start - elapsedMs) / 1000))
}
export function expiryLabel(seconds: number | null) {
  return seconds === null
    ? 'UNKNOWN'
    : `${Math.floor(seconds / 60)
        .toString()
        .padStart(2, '0')}:${(seconds % 60).toString().padStart(2, '0')}`
}
