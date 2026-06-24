import { getTimezone } from './dateFormat'

type DateInput = string | number | Date | null | undefined

const LOCAL_DATE_TIME_OPTIONS: Intl.DateTimeFormatOptions = {
  day: '2-digit',
  month: 'short',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
  hour12: true,
}

const LOCAL_DATE_ONLY_OPTIONS: Intl.DateTimeFormatOptions = {
  day: '2-digit',
  month: 'short',
  year: 'numeric',
}

const LOCAL_TIME_ONLY_OPTIONS: Intl.DateTimeFormatOptions = {
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hour12: false,
}

function parseDate(date: DateInput): Date | null {
  if (!date) return null
  const d = date instanceof Date ? date : new Date(date)
  return isNaN(d.getTime()) ? null : d
}

export function getTimezoneName(date: DateInput): string {
  const d = parseDate(date)
  if (!d) return ''
  const parts = new Intl.DateTimeFormat('en-IN', {
    timeZone: getTimezone(),
    timeZoneName: 'short',
  }).formatToParts(d)
  return parts.find((part) => part.type === 'timeZoneName')?.value ?? getTimezone()
}

export function formatLocalDateTime(
  date: DateInput,
  options: Intl.DateTimeFormatOptions = LOCAL_DATE_TIME_OPTIONS,
  includeTimezoneName = true,
): string {
  const d = parseDate(date)
  if (!d) return '—'
  const formatted = d.toLocaleString('en-IN', {
    timeZone: getTimezone(),
    ...options,
  })
  return includeTimezoneName ? `${formatted} ${getTimezoneName(d)}` : formatted
}

export function formatLocalDate(
  date: DateInput,
  includeTimezoneName = false,
): string {
  return formatLocalDateTime(date, LOCAL_DATE_ONLY_OPTIONS, includeTimezoneName)
}

export function formatLocalTime(
  date: DateInput,
  options: Intl.DateTimeFormatOptions = LOCAL_TIME_ONLY_OPTIONS,
  includeTimezoneName = true,
): string {
  return formatLocalDateTime(date, options, includeTimezoneName)
}

export function formatIST(date: DateInput, dateOnly = false): string {
  return dateOnly ? formatLocalDate(date, true) : formatLocalDateTime(date)
}

export function formatISTDate(date: DateInput): string {
  return formatIST(date, true)
}

export function formatChartDate(date: DateInput): string {
  const d = parseDate(date)
  if (!d) return ''
  return d.toLocaleString('en-IN', {
    timeZone: getTimezone(),
    month: 'short',
    day: '2-digit',
  })
}
