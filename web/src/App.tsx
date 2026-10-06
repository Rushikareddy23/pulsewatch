import { lazy, Suspense } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { AuthProvider } from './lib/auth'
import { useAuth } from './lib/authContext'
import { Dashboard } from './pages/Dashboard'
import { Layout } from './pages/Layout'
import { Login } from './pages/Login'

// Charts are only needed on the detail page, so load that code on demand.
const MonitorDetail = lazy(() => import('./pages/MonitorDetail').then(m => ({ default: m.MonitorDetail })))

function Protected() {
  const { token } = useAuth()
  return token ? <Layout /> : <Navigate to="/login" replace />
}

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route element={<Protected />}>
            <Route path="/" element={<Dashboard />} />
            <Route path="/monitors/:id" element={<Suspense fallback={<p className="text-sm text-slate-500">Loading…</p>}><MonitorDetail /></Suspense>} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  )
}
