/**
 * Tests for in-memory access-token storage (#786): the JWT must live in the
 * Zustand store (memory), never in localStorage, while a legacy localStorage
 * value is still honored as a read-time fallback during the migration.
 */
import { describe, it, expect, beforeEach } from 'vitest'
import { useAuthStore, getAccessToken, setAccessToken } from './authStore'

beforeEach(() => {
  localStorage.clear()
  setAccessToken(null)
})

describe('setAccessToken / getAccessToken', () => {
  it('stores the access token in memory and reads it back', () => {
    setAccessToken('in-memory-jwt')
    expect(getAccessToken()).toBe('in-memory-jwt')
    expect(useAuthStore.getState().accessToken).toBe('in-memory-jwt')
  })

  it('never writes the access token to localStorage', () => {
    setAccessToken('secret-jwt')
    expect(localStorage.getItem('access_token')).toBeNull()
    // The persisted store blob must not contain the token either.
    expect(localStorage.getItem('auth-store') ?? '').not.toContain('secret-jwt')
  })

  it('falls back to the legacy localStorage token when memory is empty', () => {
    localStorage.setItem('access_token', 'legacy-jwt')
    expect(getAccessToken()).toBe('legacy-jwt')
  })

  it('prefers the in-memory token over the legacy localStorage token', () => {
    localStorage.setItem('access_token', 'legacy-jwt')
    setAccessToken('fresh-jwt')
    expect(getAccessToken()).toBe('fresh-jwt')
  })

  it('returns null when neither memory nor localStorage has a token', () => {
    expect(getAccessToken()).toBeNull()
  })
})
