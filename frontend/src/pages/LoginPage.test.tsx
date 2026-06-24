/**
 * Tests for login error UX — the sign-in screen must never show raw
 * backend/proxy detail (e.g. "Not Found") to the end user.
 */
import { describe, it, expect } from 'vitest'
import { ApiError } from '../api/client'
import { loginErrorMessage } from './loginError'

describe('loginErrorMessage', () => {
  it('maps 401 to invalid credentials', () => {
    expect(loginErrorMessage(new ApiError(401, 'Invalid credentials'))).toBe(
      'Invalid email or password.',
    )
  })

  it('maps 429 to a rate-limit message', () => {
    expect(loginErrorMessage(new ApiError(429, 'rate limited'))).toMatch(/too many/i)
  })

  it('never surfaces raw "Not Found" (404) to the user', () => {
    const msg = loginErrorMessage(new ApiError(404, 'Not Found'))
    expect(msg).not.toMatch(/not found/i)
    expect(msg).toMatch(/temporarily unavailable/i)
  })

  it('maps 5xx to a temporarily-unavailable message', () => {
    const msg = loginErrorMessage(new ApiError(500, 'Internal Server Error'))
    expect(msg).not.toMatch(/internal server error/i)
    expect(msg).toMatch(/temporarily unavailable/i)
  })

  it('maps other API errors to a generic retry message', () => {
    expect(loginErrorMessage(new ApiError(400, 'Bad Request'))).toBe(
      'Unable to sign in. Please try again.',
    )
  })

  it('maps a network failure (non-ApiError) to a connectivity message', () => {
    expect(loginErrorMessage(new TypeError('Failed to fetch'))).toMatch(/can't reach the server/i)
  })
})
