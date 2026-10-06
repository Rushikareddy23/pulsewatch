import { useCallback, useState } from 'react'
import { Link } from 'react-router-dom'
import { AddMonitorForm } from '../components/AddMonitorForm'
import { StatusBadge } from '../components/StatusBadge'
import { api } from '../lib/api'
import { formatMs, formatUptime, timeAgo } from '../lib/format'
import type { Monitor, NewMonitor, Stats } from '../lib/types'
import { usePolling } from '../lib/usePolling'

export function Dashboard() {
  const [monitors, setMonitors] = useState<Monitor[] | null>(null)
  const [stats, setStats] = useState<Record<number, Stats>>({})
  const [adding, setAdding] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      const ms = await api.monitors()
      setMonitors(ms)
      const entries = await Promise.all(ms.map(async m => [m.id, await api.stats(m.id)] as const))
      setStats(Object.fromEntries(entries))
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load')
    }
  }, [])
  usePolling(load, 15000)

  async function create(m: NewMonitor) {
    await api.createMonitor(m)
    setAdding(false)
    await load()
  }

  const down = monitors?.filter(m => m.is_active && m.status === 'down').length ?? 0
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">Monitors</h1>
          {monitors && <p className="text-sm text-slate-500">
            {down ? <span className="font-medium text-red-600">{down} down</span> : 'All systems operational'} · {monitors.length} total
          </p>}
        </div>
        <button onClick={() => setAdding(true)} className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700">
          + Add monitor
        </button>
      </div>

      {adding && (
        <div className="rounded-xl bg-white p-6 shadow-sm ring-1 ring-slate-200">
          <AddMonitorForm onSubmit={create} onCancel={() => setAdding(false)} />
        </div>
      )}
      {error && <p role="alert" className="text-sm text-red-600">{error}</p>}
      {monitors === null && <p className="text-sm text-slate-500">Loading…</p>}
      {monitors?.length === 0 && !adding && (
        <div className="rounded-xl border-2 border-dashed border-slate-200 p-12 text-center text-slate-500">
          No monitors yet. Add your first website or API to start tracking uptime.
        </div>
      )}

      <ul className="divide-y divide-slate-100 overflow-hidden rounded-xl bg-white shadow-sm ring-1 ring-slate-200">
        {monitors?.map(m => (
          <li key={m.id}>
            <Link to={`/monitors/${m.id}`} className="grid grid-cols-2 items-center gap-4 px-5 py-4 hover:bg-slate-50 sm:grid-cols-[1fr_auto_auto_auto]">
              <div className="min-w-0">
                <p className="truncate font-medium">{m.name}</p>
                <p className="truncate text-xs text-slate-500">{m.url}</p>
              </div>
              <StatusBadge status={m.status} active={m.is_active} />
              <div className="text-right text-sm"><p className="font-medium">{formatUptime(stats[m.id]?.uptime_pct)}</p><p className="text-xs text-slate-500">24h uptime</p></div>
              <div className="text-right text-sm"><p className="font-medium">{formatMs(stats[m.id]?.p95_latency_ms)}</p><p className="text-xs text-slate-500">p95 · {timeAgo(m.last_checked_at)}</p></div>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  )
}
