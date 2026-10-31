import { useEffect, useRef, useState } from 'react'
import { useAuth } from './Auth'
import { errorMessage } from '../api/client'
export function useMounted() {
  const alive = useRef(true)
  useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
    }
  }, [])
  return alive
}
export function useResource<T>(path: string | null) {
  const { client } = useAuth()
  const [revision, setRevision] = useState(0)
  const [state, setState] = useState<{
    data: T | null
    error: string | null
    loading: boolean
    path: string | null
  }>({ data: null, error: null, loading: !!path, path })
  useEffect(() => {
    if (!path) return
    const controller = new AbortController()
    let active = true
    setState({ data: null, error: null, loading: true, path })
    client
      .get<T>(path, controller.signal)
      .then((data) => {
        if (active) setState({ data, error: null, loading: false, path })
      })
      .catch((error) => {
        if (active) setState({ data: null, error: errorMessage(error), loading: false, path })
      })
    return () => {
      active = false
      controller.abort()
    }
  }, [client, path, revision])
  return {
    ...state,
    data: state.path === path ? state.data : null,
    reload: () => setRevision((n) => n + 1),
  }
}
