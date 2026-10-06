export function formatUptime(pct: number | null | undefined): string {
  if (pct == null) return '—'
  if (pct === 100) return '100%'
  return `${pct.toFixed(pct >= 99 ? 2 : 1)}%`
}

export function formatMs(ms: number | null | undefined): string {
  if (ms == null) return '—'
  return ms >= 1000 ? `${(ms / 1000).toFixed(2)} s` : `${Math.round(ms)} ms`
}

export function timeAgo(iso: string | null, now: Date = new Date()): string {
  if (!iso) return 'never'
  const s = Math.max(0, Math.round((now.getTime() - new Date(iso).getTime()) / 1000))
  if (s < 60) return `${s}s ago`
  if (s < 3600) return `${Math.floor(s / 60)}m ago`
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`
  return `${Math.floor(s / 86400)}d ago`
}

export function duration(startIso: string, endIso: string | null, now: Date = new Date()): string {
  const end = endIso ? new Date(endIso) : now
  const s = Math.max(0, Math.round((end.getTime() - new Date(startIso).getTime()) / 1000))
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60)
  if (h) return `${h}h ${m}m`
  if (m) return `${m}m ${s % 60}s`
  return `${s}s`
}

export function validateMonitorUrl(url: string): string | null {
  try {
    const u = new URL(url)
    if (!['http:', 'https:'].includes(u.protocol)) return 'URL must start with http:// or https://'
    return null
  } catch {
    return 'Enter a valid URL, e.g. https://example.com'
  }
}
