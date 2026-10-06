import type { CheckPoint } from '../lib/types'

/** Last N checks as coloured ticks: the classic status-page strip. */
export function UptimeBar({ checks, n = 60 }: { checks: CheckPoint[]; n?: number }) {
  const recent = checks.slice(-n)
  return (
    <div className="flex h-8 items-end gap-[2px]" aria-label={`Last ${recent.length} checks`}>
      {recent.map((c, i) => (
        <div key={i} title={`${new Date(c.checked_at).toLocaleString()} — ${c.ok ? 'OK' : c.error}`}
          className={`h-full flex-1 rounded-sm ${c.ok ? 'bg-emerald-400' : 'bg-red-500'}`} />
      ))}
      {recent.length === 0 && <div className="h-full flex-1 rounded-sm bg-slate-200" />}
    </div>
  )
}
