import { Link, Outlet } from 'react-router-dom'
import { useAuth } from '../lib/authContext'

export function Layout() {
  const { logout } = useAuth()
  return (
    <div className="min-h-screen">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-4 py-3">
          <Link to="/" className="flex items-center gap-2 font-semibold">
            <span className="h-2.5 w-2.5 rounded-full bg-emerald-500" /> PulseWatch
          </Link>
          <button onClick={logout} className="text-sm text-slate-600 hover:text-slate-900">Sign out</button>
        </div>
      </header>
      <main className="mx-auto max-w-5xl px-4 py-8"><Outlet /></main>
    </div>
  )
}
