import { Page } from '@playwright/test'

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
 * Zustand's persist middleware reads localStorage at store creation time
 * (synchronously, before React renders). If we navigate first and then set
 * localStorage, Zustand already has null in memory and AuthGuard blocks.
 *
 * Fix: use addInitScript to inject values BEFORE the page's JavaScript runs,
 * so Zustand sees the auth-store the very first time it hydrates.
 */
export async function loginViaApi(page: Page, user = ADMIN) {
  // 1. Get tokens + user profile from API (no browser involved yet)
  const loginRes = await page.request.post(`${API}/auth/login`, {
    data: { email: user.email, password: user.password },
  })
  const { access_token, refresh_token } = await loginRes.json()

  const meRes = await page.request.get(`${API}/auth/me`, {
    headers: { Authorization: `Bearer ${access_token}` },
  })
  const me = await meRes.json()

  // 2. Inject into localStorage BEFORE any navigation so Zustand reads them on init
  await page.addInitScript(({ at, rt, me }) => {
    localStorage.setItem('access_token', at)
    localStorage.setItem('refresh_token', rt)
    localStorage.setItem('auth-store', JSON.stringify({ state: { user: me }, version: 0 }))
  }, { at: access_token, rt: refresh_token, me })

  // 3. Navigate — Zustand will hydrate with the user already set
  await page.goto('/fleet')
  await page.waitForSelector('h1:has-text("Fleet Dashboard")', { timeout: 12000 })
}
