import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { api, tokenStore, UNAUTHORIZED_EVENT } from './api'
import { AuthContext } from './authContext'

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(tokenStore.get())
  const save = (t: string) => { tokenStore.set(t); setToken(t) }
  const login = useCallback(async (e: string, p: string) => save((await api.login(e, p)).access_token), [])
  const register = useCallback(async (e: string, p: string) => save((await api.register(e, p)).access_token), [])
  const logout = useCallback(() => { tokenStore.clear(); setToken(null) }, [])
  // Expired/revoked token: clear React state too, which redirects protected pages to /login.
  useEffect(() => {
    window.addEventListener(UNAUTHORIZED_EVENT, logout)
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, logout)
  }, [logout])
  return <AuthContext.Provider value={{ token, login, register, logout }}>{children}</AuthContext.Provider>
}
