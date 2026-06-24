import { afterEach, describe, expect, it, vi } from 'vitest'
import { getTimezone } from './dateFormat'

describe('getTimezone', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('uses the browser resolved timezone', () => {
    vi.spyOn(Intl.DateTimeFormat.prototype, 'resolvedOptions').mockReturnValue({
      timeZone: 'America/New_York',
    } as Intl.ResolvedDateTimeFormatOptions)

    expect(getTimezone()).toBe('America/New_York')
  })
})
