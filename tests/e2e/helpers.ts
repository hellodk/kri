import { APIRequestContext, Page } from '@playwright/test'

export const BASE = 'http://localhost:5173'
export const API  = 'http://localhost:8000'

export const ADMIN  = { email: 'admin@fleet.local',  password: 'changeme' }
export const VIEWER = { email: 'viewer@fleet.local', password: 'changeme' }

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
 * Key constraint: Zustand's persist middleware reads localStorage synchronously
 * at store creation (first render). We must inject BEFORE navigating so the
 * store hydrates with the correct user — use addInitScript for this.
 *
 * We do NOT use waitForLoadState('networkidle') because TanStack Query's
 * background polling keeps the network busy indefinitely.
 */
export async function loginViaApi(page: Page, user = ADMIN) {
  // 1. Get tokens + user profile (no browser involved yet)
  const loginRes = await page.request.post(`${API}/auth/login`, {
    data: { email: user.email, password: user.password },
  })
  const { access_token, refresh_token } = await loginRes.json()

  const meRes = await page.request.get(`${API}/auth/me`, {
    headers: { Authorization: `Bearer ${access_token}` },
  })
  const me = await meRes.json()

  // 2. Inject into localStorage BEFORE first navigation — runs before page JS
  await page.addInitScript(({ at, rt, me }) => {
    localStorage.setItem('access_token', at)
    localStorage.setItem('refresh_token', rt)
    // Zustand persist key — must match { name: 'auth-store' } in authStore.ts
    localStorage.setItem('auth-store', JSON.stringify({ state: { user: me }, version: 0 }))
  }, { at: access_token, rt: refresh_token, me })

  // 3. Navigate — avoid networkidle, TanStack Query polls indefinitely
  await page.goto('/fleet')
  await page.waitForURL('**/fleet', { timeout: 10000 })
  await page.locator('h1').first().waitFor({ state: 'visible', timeout: 15000 })
}

/** Get a fresh Bearer token for API-only tests */
export async function getToken(request: APIRequestContext, user = ADMIN): Promise<string> {
  const res = await request.post(`${API}/auth/login`, {
    data: { email: user.email, password: user.password },
  })
  const body = await res.json()
  return body.access_token as string
}
