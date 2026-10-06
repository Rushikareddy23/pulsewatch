import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { CheckPoint } from '../lib/types'

export function LatencyChart({ checks }: { checks: CheckPoint[] }) {
  const data = checks.map(c => ({
    t: new Date(c.checked_at).getTime(),
    latency: c.ok ? c.latency_ms : null,
  }))
  if (!data.length) return <p className="py-16 text-center text-sm text-slate-500">No checks yet. The first one runs within a minute.</p>
  return (
    <div className="h-64">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid stroke="#e2e8f0" vertical={false} />
          <XAxis dataKey="t" type="number" domain={['dataMin', 'dataMax']} scale="time" tick={{ fontSize: 11 }}
            tickFormatter={t => new Date(t).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })} />
          <YAxis tick={{ fontSize: 11 }} width={64} unit=" ms" />
          <Tooltip labelFormatter={t => new Date(Number(t)).toLocaleString()} formatter={v => [`${v} ms`, 'Response time']} />
          <Line type="monotone" dataKey="latency" stroke="#4f46e5" strokeWidth={2} dot={false} connectNulls={false} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
