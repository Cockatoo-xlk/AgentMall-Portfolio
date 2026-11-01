import { useEffect, useRef, useState } from 'react'
import type { Proposal } from '../api/types'
import { proposalRemaining } from '../api/proposalExpiry'

export function useProposalExpiry(proposal: Proposal | null, reload: () => void) {
  const [remaining, setRemaining] = useState<number | null>(null)
  const lastChecked = useRef('')
  const refresh = useRef(reload)
  useEffect(() => {
    refresh.current = reload
  }, [reload])
  const id = proposal?.proposal_id
  const expires = proposal?.expires_at
  const server = proposal?.server_time
  const pending = proposal?.status === 'PENDING' && !proposal.confirmation && !proposal.result
  useEffect(() => {
    setRemaining(null)
    if (!id || !expires || !pending) return
    const anchor = performance.now()
    function tick() {
      const seconds = proposalRemaining(
        expires!,
        server,
        Math.max(0, performance.now() - anchor),
      )
      setRemaining(seconds)
      // One read per immutable deadline, not a paid request or automatic decision.
      const key = `${id}:${expires}`
      if (seconds === 0 && lastChecked.current !== key) {
        lastChecked.current = key
        refresh.current()
      }
    }
    tick()
    const timer = setInterval(tick, 1000)
    return () => clearInterval(timer)
  }, [id, expires, server, pending])
  return { remaining, elapsed: pending && remaining === 0 }
}
