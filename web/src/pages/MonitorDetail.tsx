import { useCallback, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { LatencyChart } from '../components/LatencyChart'
import { StatusBadge } from '../components/StatusBadge'
import { UptimeBar } from '../components/UptimeBar'
import { api } from '../lib/api'
import { duration, formatMs, formatUptime } from '../lib/format'
import type { CheckPoint, Incident, Monitor, Stats } from '../lib/types'
import { usePolling } from '../lib/usePolling'

const RANGES = [1, 24, 168] as const

export function MonitorDetail() {
  const id = Number(useParams().id)
  const nav = useNavigate()
  const [hours, setHours] = useState<number>(24)
  const [monitor, setMonitor] = useState<Monitor | null>(null)
  const [checks, setChecks] = useState<CheckPoint[]>([])
  const [incidents, setIncidents] = useState<Incident[]>([])
  const [stats, setStats] = useState<Stats | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      const [m, c, i, s] = await Promise.all([api.monitor(id), api.checks(id, hours), api.incidents(id), api.stats(id, hours)])
      setMonitor(m); setChecks(c); setIncidents(i); setStats(s); setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load')
    }
  }, [id, hours])
  usePolling(load, 15000)

  async function toggle() {
    if (!monitor) return
    setMonitor(await api.updateMonitor(id, { is_active: !monitor.is_active }))
  }
  async function remove() {
    if (window.confirm(`Delete "${monitor?.name}" and all its history?`)) {
      await api.deleteMonitor(id)
      nav('/')
    }
  }

  if (error) return <p role="alert" className="text-red-600">{error}</p>
  if (!monitor) return <p className="text-sm text-slate-500">Loading…</p>
  const card = 'rounded-xl bg-white p-5 shadow-sm ring-1 ring-slate-200'
  return (
    <div className="space-y-6">
      <Link to="/" className="text-sm text-indigo-600 hover:underline">← All monitors</Link>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-3"><h1 className="text-xl font-semibold">{monitor.name}</h1><StatusBadge status={monitor.status} active={monitor.is_active} /></div>
          <a href={monitor.url} target="_blank" rel="noreferrer" className="text-sm text-slate-500 hover:underline">{monitor.url}</a>
        </div>
        <div className="flex gap-2">
          <button onClick={toggle} className="rounded-md px-3 py-1.5 text-sm ring-1 ring-slate-300 hover:bg-slate-50">{monitor.is_active ? 'Pause' : 'Resume'}</button>
          <button onClick={remove} className="rounded-md px-3 py-1.5 text-sm text-red-600 ring-1 ring-red-200 hover:bg-red-50">Delete</button>
        </div>
      </div>

      <div className="flex gap-1 text-sm">
        {RANGES.map(h => (
          <button key={h} onClick={() => setHours(h)} className={`rounded-md px-3 py-1 ${h === hours ? 'bg-slate-900 text-white' : 'text-slate-600 hover:bg-slate-100'}`}>
            {h === 168 ? '7d' : `${h}h`}
          </button>
        ))}
      </div>

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        {[['Uptime', formatUptime(stats?.uptime_pct)], ['Avg response', formatMs(stats?.avg_latency_ms)],
          ['p95 response', formatMs(stats?.p95_latency_ms)], ['Incidents', String(stats?.incidents ?? '—')]].map(([k, v]) => (
          <div key={k} className={card}><p className="text-xs text-slate-500">{k}</p><p className="mt-1 text-2xl font-semibold">{v}</p></div>
        ))}
      </div>

      <div className={card}><h2 className="mb-3 text-sm font-medium">Recent checks</h2><UptimeBar checks={checks} /></div>
      <div className={card}><h2 className="mb-3 text-sm font-medium">Response time</h2><LatencyChart checks={checks} /></div>

      <div className={card}>
        <h2 className="mb-3 text-sm font-medium">Incidents</h2>
        {incidents.length === 0 ? <p className="text-sm text-slate-500">No incidents. Nice.</p> : (
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-slate-500"><tr><th className="pb-2">Started</th><th>Duration</th><th>Cause</th></tr></thead>
            <tbody className="divide-y divide-slate-100">
              {incidents.map(i => (
                <tr key={i.id}>
                  <td className="py-2">{new Date(i.started_at).toLocaleString()}</td>
                  <td>{i.resolved_at ? duration(i.started_at, i.resolved_at) : <span className="font-medium text-red-600">Ongoing · {duration(i.started_at, null)}</span>}</td>
                  <td className="text-slate-600">{i.cause}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
