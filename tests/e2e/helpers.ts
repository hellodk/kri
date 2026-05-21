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
  await page.waitForURL('**/fleet', { timeout: 8000 })
}

/**
 * Log in via API and inject tokens + Zustand auth-store into localStorage.
 * Skips the login UI entirely — ~4× faster than login().
 * AuthGuard checks both localStorage tokens AND the Zustand persisted user,
 * so we must populate both.
 */
export async function loginViaApi(page: Page, user = ADMIN) {
  // 1. Get tokens
  const loginRes = await page.request.post(`${API}/auth/login`, {
    data: { email: user.email, password: user.password },
  })
  const { access_token, refresh_token } = await loginRes.json()

  // 2. Get user profile
  const meRes = await page.request.get(`${API}/auth/me`, {
    headers: { Authorization: `Bearer ${access_token}` },
  })
  const me = await meRes.json()

  // 3. Inject everything into a blank page before navigating to the app
  await page.goto('about:blank')
  await page.evaluate(({ at, rt, me }) => {
    localStorage.setItem('access_token', at)
    localStorage.setItem('refresh_token', rt)
    // Populate Zustand persisted auth-store so AuthGuard passes
    localStorage.setItem('auth-store', JSON.stringify({ state: { user: me }, version: 0 }))
  }, { at: access_token, rt: refresh_token, me })

  await page.goto('/fleet')
  await page.waitForSelector('h1:has-text("Fleet Dashboard")', { timeout: 8000 })
}
