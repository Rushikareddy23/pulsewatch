import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { AddMonitorForm } from './AddMonitorForm'
import { StatusBadge } from './StatusBadge'

describe('StatusBadge', () => {
  it('shows status, or Paused when inactive', () => {
    const { rerender } = render(<StatusBadge status="down" />)
    expect(screen.getByText('Down')).toBeInTheDocument()
    rerender(<StatusBadge status="down" active={false} />)
    expect(screen.getByText('Paused')).toBeInTheDocument()
  })
})

describe('AddMonitorForm', () => {
  it('blocks invalid input without calling the API', async () => {
    const onSubmit = vi.fn()
    render(<AddMonitorForm onSubmit={onSubmit} />)
    await userEvent.click(screen.getByRole('button', { name: /add monitor/i }))
    expect(screen.getByRole('alert')).toHaveTextContent(/name/i)
    await userEvent.type(screen.getByLabelText(/name/i), 'Site')
    await userEvent.clear(screen.getByLabelText(/url/i))
    await userEvent.type(screen.getByLabelText(/url/i), 'not-a-url')
    await userEvent.click(screen.getByRole('button', { name: /add monitor/i }))
    expect(screen.getByRole('alert')).toHaveTextContent(/valid URL/i)
    expect(onSubmit).not.toHaveBeenCalled()
  })

  it('submits a valid monitor and shows server errors', async () => {
    const onSubmit = vi.fn().mockRejectedValueOnce(new Error('URL points to a private or internal address'))
    render(<AddMonitorForm onSubmit={onSubmit} />)
    await userEvent.type(screen.getByLabelText(/name/i), 'Blog')
    await userEvent.type(screen.getByLabelText(/url/i), 'example.com')
    await userEvent.selectOptions(screen.getByLabelText(/check every/i), '300')
    await userEvent.click(screen.getByRole('button', { name: /add monitor/i }))
    expect(onSubmit).toHaveBeenCalledWith({ name: 'Blog', url: 'https://example.com', method: 'GET', interval_s: 300, expected_status: 200 })
    expect(await screen.findByRole('alert')).toHaveTextContent(/private/)
  })
})
