/**
 * Tests for the WebSocket connection helpers that keep auth off the query string
 * (#783) and pick the right ws/wss scheme on HTTPS (#784).
 */
import { describe, it, expect } from 'vitest'
import { wsScheme, wsUrl, wsAuthProtocols } from './client'

describe('wsScheme', () => {
  it('uses wss: when the page is served over https:', () => {
    expect(wsScheme('https:')).toBe('wss:')
  })

  it('uses ws: for http: (and anything that is not https:)', () => {
    expect(wsScheme('http:')).toBe('ws:')
  })

  it('defaults to the page protocol (jsdom serves http) when no arg is given', () => {
    // jsdom's default location is http://localhost:3000 → ws:
    expect(wsScheme()).toBe('ws:')
  })
})

describe('wsUrl', () => {
  it('builds a same-origin ws URL under the jsdom (http) test environment', () => {
    // jsdom default host is localhost:3000
    expect(wsUrl('/api/v1/ssh/session/abc')).toBe('ws://localhost:3000/api/v1/ssh/session/abc')
  })

  it('normalizes a path that is missing its leading slash', () => {
    expect(wsUrl('api/v1/vnc/session/xyz')).toBe('ws://localhost:3000/api/v1/vnc/session/xyz')
  })

  it('preserves an existing query string', () => {
    expect(wsUrl('/api/v1/ssh/session/n?token=t')).toBe(
      'ws://localhost:3000/api/v1/ssh/session/n?token=t',
    )
  })
})

describe('wsAuthProtocols', () => {
  it('carries the JWT as the second subprotocol so it never hits the URL', () => {
    expect(wsAuthProtocols('jwt-token-value')).toEqual(['jwt', 'jwt-token-value'])
  })

  it('returns an empty list when there is no token', () => {
    expect(wsAuthProtocols(null)).toEqual([])
    expect(wsAuthProtocols(undefined)).toEqual([])
    expect(wsAuthProtocols('')).toEqual([])
  })
})
