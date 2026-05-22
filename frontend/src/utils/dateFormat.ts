import { format, formatDistanceToNow } from 'date-fns'
import { toZonedTime } from 'date-fns-tz'

export function getTimezone(): string {
  return localStorage.getItem('kri_timezone') || Intl.DateTimeFormat().resolvedOptions().timeZone
}

export function formatDate(date: string | Date, fmt = 'PPpp'): string {
  const d = typeof date === 'string' ? new Date(date) : date
  return format(toZonedTime(d, getTimezone()), fmt)
}

export function formatRelative(date: string | Date): string {
  return formatDistanceToNow(new Date(date as string), { addSuffix: true })
}
