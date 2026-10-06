import type { CheckPoint, Incident, Monitor, NewMonitor, Stats } from './types'

const TOKEN_KEY = 'pulsewatch.token'

export const tokenStore = {
  get: (): string | null => { try { return localStorage.getItem(TOKEN_KEY) } catch { return null } },
  set: (t: string) => { try { localStorage.setItem(TOKEN_KEY, t) } catch { /* private mode */ } },
  clear: () => { try { localStorage.removeItem(TOKEN_KEY) } catch { /* ignore */ } },
}

/** Fired when the server rejects our token (expired or revoked), so the UI can sign out. */
export const UNAUTHORIZED_EVENT = 'pulsewatch:unauthorized'

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = tokenStore.get()
  const res = await fetch(`/api${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...init.headers,
    },
  })
  if (res.status === 401 && token) {
    tokenStore.clear()
    window.dispatchEvent(new Event(UNAUTHORIZED_EVENT))
  }
  if (!res.ok) {
    let msg = res.statusText
    try {
      const body = await res.json()
      msg = typeof body.detail === 'string' ? body.detail : body.detail?.[0]?.msg ?? msg
    } catch { /* non-JSON error */ }
    throw new ApiError(res.status, msg)
  }
  return (res.status === 204 ? undefined : await res.json()) as T
}

export const api = {
  register: (email: string, password: string) =>
    request<{ access_token: string }>('/auth/register', { method: 'POST', body: JSON.stringify({ email, password }) }),
  login: (email: string, password: string) =>
    request<{ access_token: string }>('/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) }),
  me: () => request<{ id: number; email: string }>('/auth/me'),
  monitors: () => request<Monitor[]>('/monitors'),
  monitor: (id: number) => request<Monitor>(`/monitors/${id}`),
  createMonitor: (m: NewMonitor) => request<Monitor>('/monitors', { method: 'POST', body: JSON.stringify(m) }),
  updateMonitor: (id: number, patch: Partial<Monitor>) =>
    request<Monitor>(`/monitors/${id}`, { method: 'PATCH', body: JSON.stringify(patch) }),
  deleteMonitor: (id: number) => request<void>(`/monitors/${id}`, { method: 'DELETE' }),
  checks: (id: number, hours = 24) => request<CheckPoint[]>(`/monitors/${id}/checks?hours=${hours}`),
  incidents: (id: number) => request<Incident[]>(`/monitors/${id}/incidents`),
  stats: (id: number, hours = 24) => request<Stats>(`/monitors/${id}/stats?hours=${hours}`),
}
