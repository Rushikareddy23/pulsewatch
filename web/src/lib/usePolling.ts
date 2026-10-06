import { useEffect, useRef } from 'react'

/**
 * Calls `fn` immediately, again whenever `fn` changes (e.g. the user picks a new time range),
 * and every `ms` milliseconds while the tab is visible.
 */
export function usePolling(fn: () => void, ms: number) {
  const saved = useRef(fn)
  useEffect(() => {
    saved.current = fn
    fn()
  }, [fn])
  useEffect(() => {
    const id = setInterval(() => { if (!document.hidden) saved.current() }, ms)
    return () => clearInterval(id)
  }, [ms])
}
