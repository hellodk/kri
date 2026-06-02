/**
 * IST time formatting utilities.
 * All timestamps shown to users must be in IST (Asia/Kolkata, UTC+5:30).
 * Relative times (formatDistanceToNow) are left unchanged — they convey
 * "how long ago" which needs no timezone conversion.
 */

const IST_OPTIONS: Intl.DateTimeFormatOptions = {
  timeZone: 'Asia/Kolkata',
  day: '2-digit',
  month: 'short',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
  hour12: true,
}

const IST_DATE_ONLY: Intl.DateTimeFormatOptions = {
  timeZone: 'Asia/Kolkata',
  day: '2-digit',
  month: 'short',
  year: 'numeric',
}

/**
 * Format a date as "02 Jun 2026, 11:44 PM IST"
 * Pass `dateOnly: true` for "02 Jun 2026 IST" (no time component).
 */
export function formatIST(date: string | Date | null | undefined, dateOnly = false): string {
  if (!date) return '—'
  const d = typeof date === 'string' ? new Date(date) : date
  if (isNaN(d.getTime())) return '—'
  const opts = dateOnly ? IST_DATE_ONLY : IST_OPTIONS
  return d.toLocaleString('en-IN', opts) + ' IST'
}

/** Short date only: "02 Jun 2026 IST" */
export function formatISTDate(date: string | Date | null | undefined): string {
  return formatIST(date, true)
}

/** Month/day only for charts: "Jun 02" — no timezone conversion needed */
export function formatChartDate(date: string | Date | null | undefined): string {
  if (!date) return ''
  const d = typeof date === 'string' ? new Date(date) : date
  if (isNaN(d.getTime())) return ''
  return d.toLocaleString('en-IN', {
    timeZone: 'Asia/Kolkata',
    month: 'short',
    day: '2-digit',
  })
}
