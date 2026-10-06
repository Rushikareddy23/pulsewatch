import type { MonitorStatus } from '../lib/types'

const STYLES: Record<MonitorStatus | 'paused', { dot: string; text: string; label: string }> = {
  up: { dot: 'bg-emerald-500', text: 'text-emerald-700 bg-emerald-50', label: 'Up' },
  down: { dot: 'bg-red-500 animate-pulse', text: 'text-red-700 bg-red-50', label: 'Down' },
  pending: { dot: 'bg-amber-400', text: 'text-amber-700 bg-amber-50', label: 'Pending' },
  paused: { dot: 'bg-slate-400', text: 'text-slate-600 bg-slate-100', label: 'Paused' },
}

export function StatusBadge({ status, active = true }: { status: MonitorStatus; active?: boolean }) {
  const s = STYLES[active ? status : 'paused']
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium ${s.text}`}>
      <span aria-hidden className={`h-2 w-2 rounded-full ${s.dot}`} />
      {s.label}
    </span>
  )
}
