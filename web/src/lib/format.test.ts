import { describe, expect, it } from 'vitest'
import { duration, formatMs, formatUptime, timeAgo, validateMonitorUrl } from './format'

describe('format helpers', () => {
  it('formats uptime with more precision near 100%', () => {
    expect(formatUptime(100)).toBe('100%')
    expect(formatUptime(99.957)).toBe('99.96%')
    expect(formatUptime(87.25)).toBe('87.3%')
    expect(formatUptime(null)).toBe('—')
  })
  it('formats latency', () => {
    expect(formatMs(42.4)).toBe('42 ms')
    expect(formatMs(1530)).toBe('1.53 s')
  })
  it('formats relative time and durations', () => {
    const now = new Date('2026-01-01T12:00:00Z')
    expect(timeAgo('2026-01-01T11:59:30Z', now)).toBe('30s ago')
    expect(timeAgo('2026-01-01T09:00:00Z', now)).toBe('3h ago')
    expect(timeAgo(null, now)).toBe('never')
    expect(duration('2026-01-01T10:00:00Z', '2026-01-01T11:05:00Z')).toBe('1h 5m')
  })
  it('validates monitor URLs', () => {
    expect(validateMonitorUrl('https://example.com')).toBeNull()
    expect(validateMonitorUrl('ftp://example.com')).toMatch(/http/)
    expect(validateMonitorUrl('nope')).toMatch(/valid URL/)
  })
})
