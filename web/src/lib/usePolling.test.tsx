import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useCallback, useState } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { usePolling } from './usePolling'

function Probe({ fetchFor }: { fetchFor: (hours: number) => void }) {
  const [hours, setHours] = useState(24)
  const load = useCallback(() => fetchFor(hours), [fetchFor, hours])
  usePolling(load, 15000)
  return <button onClick={() => setHours(1)}>1h</button>
}

afterEach(() => vi.useRealTimers())

describe('usePolling', () => {
  it('refreshes immediately when the range changes, not 15 s later', async () => {
    const fetchFor = vi.fn()
    render(<Probe fetchFor={fetchFor} />)
    expect(fetchFor).toHaveBeenLastCalledWith(24)
    await userEvent.click(screen.getByRole('button', { name: '1h' }))
    expect(fetchFor).toHaveBeenLastCalledWith(1)
  })

  it('keeps polling on the interval with the latest callback', () => {
    vi.useFakeTimers()
    const fetchFor = vi.fn()
    render(<Probe fetchFor={fetchFor} />)
    const before = fetchFor.mock.calls.length
    act(() => { vi.advanceTimersByTime(15000) })
    expect(fetchFor.mock.calls.length).toBe(before + 1)
  })
})
