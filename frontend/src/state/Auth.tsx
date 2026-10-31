import { createContext, useContext, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { ApiClient } from '../api/client'
import type { User } from '../api/types'
interface AuthValue {
  user: User | null
  client: ApiClient
  expired: boolean
  login: (login: string, password: string) => Promise<void>
  logout: () => void
}
const Context = createContext<AuthValue | null>(null)
export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<{ token: string; user: User } | null>(null)
  const [expired, setExpired] = useState(false)
  const epoch = useRef(0)
  const client = useMemo(() => {
    const current = epoch.current
    return new ApiClient(session?.token ?? null, () => {
      if (current === epoch.current) {
        epoch.current++
        setSession(null)
        setExpired(true)
      }
    })
  }, [session])
  async function login(login: string, password: string) {
    const current = ++epoch.current
    const token = await new ApiClient().post<{ access_token: string }>('/auth/login', {
      login,
      password,
    })
    const user = await new ApiClient(token.access_token).get<User>('/me')
    if (current === epoch.current) {
      setSession({ token: token.access_token, user })
      setExpired(false)
    }
  }
  function logout() {
    epoch.current++
    setSession(null)
    setExpired(false)
  }
  return (
    <Context.Provider value={{ user: session?.user ?? null, client, expired, login, logout }}>
      {children}
    </Context.Provider>
  )
}
export function useAuth() {
  const value = useContext(Context)
  if (!value) throw new Error('AuthProvider missing')
  return value
}
