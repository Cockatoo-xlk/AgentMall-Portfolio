import { useRef, useState } from 'react'
import { ApiError, errorMessage } from '../api/client'
import { useMounted } from './useResource'

export function useMerchantAction(reload: () => void) {
  const running = useRef(false)
  const alive = useMounted()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function run(action: () => Promise<void>, refresh = false) {
    if (running.current) return
    running.current = true
    setBusy(true)
    setError(null)
    try {
      await action()
      if (alive.current && refresh) reload()
    } catch (cause) {
      if (!alive.current) return
      const stale = cause instanceof ApiError && cause.code === 'STALE_VERSION'
      setError(stale ? '版本已变化，请核对重新加载的状态，再决定是否操作。' : errorMessage(cause))
      if (cause instanceof ApiError && (cause.status === 409 || cause.ambiguous)) reload()
    } finally {
      running.current = false
      if (alive.current) setBusy(false)
    }
  }

  return { busy, error, run }
}
