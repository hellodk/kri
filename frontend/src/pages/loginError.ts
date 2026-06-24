import { ApiError } from '../api/client'

/**
 * Translate a login failure into a message safe to show an end user.
 *
 * Never surface raw backend/proxy detail (e.g. "Not Found", "Internal Server
 * Error") on the sign-in screen — it's confusing and leaks implementation
 * detail. Map by HTTP status to a friendly, actionable message instead.
 */
export function loginErrorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 401) return 'Invalid email or password.'
    if (err.status === 429) return 'Too many sign-in attempts. Please wait a moment and try again.'
    if (err.status === 404 || err.status >= 500) {
      return 'Sign-in is temporarily unavailable. Please try again shortly.'
    }
    return 'Unable to sign in. Please try again.'
  }
  // fetch() rejects with a TypeError when the server is unreachable.
  return "Can't reach the server. Check your connection and try again."
}
