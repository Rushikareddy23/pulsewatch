import { render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from './App'

afterEach(() => { vi.unstubAllGlobals(); localStorage.clear(); window.history.pushState({}, '', '/') })

describe('session expiry', () => {
  it('signs out and shows the login page when the API returns 401', async () => {
    localStorage.setItem('pulsewatch.token', 'expired-token')
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: 'Invalid or missing token' }), { status: 401 })))
    render(<App />)
    expect(await screen.findByRole('button', { name: /sign in/i })).toBeInTheDocument()
    expect(localStorage.getItem('pulsewatch.token')).toBeNull()
  })

  it('stays on the dashboard with a valid session', async () => {
    localStorage.setItem('pulsewatch.token', 'good-token')
    vi.stubGlobal('fetch', vi.fn().mockImplementation(async () => new Response('[]', { status: 200 })))
    render(<App />)
    expect(await screen.findByText(/no monitors yet/i)).toBeInTheDocument()
  })
})
