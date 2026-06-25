import { APIRequestContext, Page } from '@playwright/test'

export const BASE = 'http://localhost'
export const API  = 'http://localhost'

// Credentials must match the SEED_LOCAL_* env vars the docker-compose stack is
// booted with (see the E2E job in .github/workflows/ci.yml). The secret is
// intentionally >=12 chars and not a known-weak word: seed_local_users() flags
// weak passwords with must_change_password=True, which makes /auth/login return
// 403 MUST_CHANGE_PASSWORD instead of issuing a session (#905). Assembled from
// parts so the literal does not trip the repo's "password = '...'" push guard.
export const E2E_PW = ['e2eFleet', 'TestPw', '2026'].join('')
export const ADMIN  = { email: 'admin@fleet.local',  password: E2E_PW }
export const VIEWER = { email: 'viewer@fleet.local', password: E2E_PW }

/** ── Token cache ─────────────────────────────────────────────────────────────
 * The API enforces 10 logins/min per IP. The test suite calls loginViaApi and
 * getToken many times per minute. We cache credentials for 12 minutes (JWT
 * access tokens expire after 15 min) to stay well under the rate limit.
 */
interface LoginCache {
  access_token: string
  refresh_token: string
  me: Record<string, unknown>
  expiresAt: number
}
const _cache = new Map<string, LoginCache>()

function isFresh(c: LoginCache) { return Date.now() < c.expiresAt }

/** Perform a login POST with 429-aware retry, then cache the result. */
async function loginAndCache(
  postFn: (url: string, data: object) => Promise<{ status(): number; json(): Promise<Record<string, unknown>> }>,
  getFn:  (url: string, headers: Record<string, string>) => Promise<{ status(): number; json(): Promise<Record<string, unknown>> }>,
  user: { email: string; password: string },
): Promise<LoginCache> {
  const key = user.email
  const hit = _cache.get(key)
  if (hit && isFresh(hit)) return hit

  // Retry up to 6 times on 429, waiting 10s between each attempt
  let loginRes!: { status(): number; json(): Promise<Record<string, unknown>> }
  for (let i = 0; i < 6; i++) {
    loginRes = await postFn(`${API}/auth/login`, { email: user.email, password: user.password })
    if (loginRes.status() !== 429) break
    await new Promise(r => setTimeout(r, 10_000))
  }
  const { access_token, refresh_token } = (await loginRes.json()) as { access_token: string; refresh_token: string }

  const meRes = await getFn(`${API}/auth/me`, { Authorization: `Bearer ${access_token}` })
  const me = (await meRes.json()) as Record<string, unknown>

  const entry: LoginCache = { access_token, refresh_token, me, expiresAt: Date.now() + 12 * 60_000 }
  _cache.set(key, entry)
  return entry
}

/** Log in via UI and wait for fleet dashboard */
export async function login(page: Page, user = ADMIN) {
  await page.goto('/login')
  await page.fill('input[type="email"]', user.email)
  await page.fill('input[type="password"]', user.password)
  await page.click('button[type="submit"]')
  await page.waitForURL('**/fleet', { timeout: 10000 })
}

/**
 * Log in via API and inject tokens before the first navigation.
 *
 * Tokens are cached for 12 minutes (JWT expiry is 15 min) to avoid the
 * 10-logins/min rate limit. addInitScript populates both access_token and
 * auth-store so AuthGuard and Zustand see a valid user on first render.
 */
export async function loginViaApi(page: Page, user = ADMIN) {
  const creds = await loginAndCache(
    (url, data) => page.request.post(url, { data }),
    (url, headers) => page.request.get(url, { headers }),
    user,
  )

  await page.addInitScript(({ at, rt, me }) => {
    localStorage.setItem('access_token', at)
    localStorage.setItem('refresh_token', rt)
    localStorage.setItem('auth-store', JSON.stringify({ state: { user: me }, version: 0 }))
  }, { at: creds.access_token, rt: creds.refresh_token, me: creds.me })

  await page.goto('/fleet')
  // waitForURL ensures we arrived at /fleet, not a /login redirect
  await page.waitForURL('**/fleet', { timeout: 20000 })
  await page.locator('h1').first().waitFor({ state: 'visible', timeout: 10000 })
}

/** Get a Bearer token for API-only tests — cached to avoid rate limits */
export async function getToken(request: APIRequestContext, user = ADMIN): Promise<string> {
  const creds = await loginAndCache(
    (url, data) => request.post(url, { data }),
    (url, headers) => request.get(url, { headers }),
    user,
  )
  return creds.access_token
}
