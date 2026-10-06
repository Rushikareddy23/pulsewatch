export type MonitorStatus = 'pending' | 'up' | 'down'

export interface Monitor {
  id: number
  name: string
  url: string
  method: 'GET' | 'HEAD'
  interval_s: number
  timeout_s: number
  expected_status: number
  is_active: boolean
  status: MonitorStatus
  last_checked_at: string | null
  created_at: string
}

export interface CheckPoint {
  checked_at: string
  ok: boolean
  status_code: number | null
  latency_ms: number | null
  error: string | null
}

export interface Incident {
  id: number
  started_at: string
  resolved_at: string | null
  cause: string
}

export interface Stats {
  hours: number
  checks: number
  uptime_pct: number | null
  avg_latency_ms: number | null
  p95_latency_ms: number | null
  incidents: number
}

export interface NewMonitor {
  name: string
  url: string
  method: 'GET' | 'HEAD'
  interval_s: number
  expected_status: number
}
