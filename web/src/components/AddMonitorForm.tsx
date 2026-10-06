import { useState, type FormEvent } from 'react'
import { validateMonitorUrl } from '../lib/format'
import type { NewMonitor } from '../lib/types'

interface Props {
  onSubmit: (m: NewMonitor) => Promise<void>
  onCancel?: () => void
}

export function AddMonitorForm({ onSubmit, onCancel }: Props) {
  const [name, setName] = useState('')
  const [url, setUrl] = useState('https://')
  const [interval, setInterval] = useState(60)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(e: FormEvent) {
    e.preventDefault()
    const urlError = validateMonitorUrl(url)
    if (!name.trim()) return setError('Give the monitor a name')
    if (urlError) return setError(urlError)
    setError(null)
    setBusy(true)
    try {
      await onSubmit({ name: name.trim(), url, method: 'GET', interval_s: interval, expected_status: 200 })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not create monitor')
    } finally {
      setBusy(false)
    }
  }

  const input = 'mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500'
  return (
    <form onSubmit={submit} className="space-y-4" noValidate>
      <label className="block text-sm font-medium">Name
        <input className={input} value={name} onChange={e => setName(e.target.value)} placeholder="My portfolio" />
      </label>
      <label className="block text-sm font-medium">URL
        <input className={input} value={url} onChange={e => setUrl(e.target.value)} />
      </label>
      <label className="block text-sm font-medium">Check every
        <select className={input} value={interval} onChange={e => setInterval(Number(e.target.value))}>
          <option value={30}>30 seconds</option>
          <option value={60}>1 minute</option>
          <option value={300}>5 minutes</option>
          <option value={900}>15 minutes</option>
        </select>
      </label>
      {error && <p role="alert" className="text-sm text-red-600">{error}</p>}
      <div className="flex justify-end gap-2">
        {onCancel && <button type="button" onClick={onCancel} className="rounded-md px-4 py-2 text-sm text-slate-600 hover:bg-slate-100">Cancel</button>}
        <button disabled={busy} className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50">
          {busy ? 'Adding…' : 'Add monitor'}
        </button>
      </div>
    </form>
  )
}
