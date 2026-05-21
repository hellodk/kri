import { Page } from '@playwright/test'

export const BASE = 'http://localhost:5173'
export const API  = 'http://localhost:8000'

export const ADMIN = { email: 'admin@fleet.local', password: 'changeme' }
export const VIEWER = { email: 'viewer@fleet.local', password: 'changeme' }

/** Log in via UI and wait for fleet dashboard */
export async function login(page: Page, user = ADMIN) {
  await page.goto('/login')
  await page.fill('input[type="email"]', user.email)
  await page.fill('input[type="password"]', user.password)
  await page.click('button[type="submit"]')
  await page.waitForURL('**/fleet', { timeout: 8000 })
}

/** Log in via API and inject tokens into localStorage (faster — skips UI) */
export async function loginViaApi(page: Page, user = ADMIN) {
  const res = await page.request.post(`${API}/auth/login`, {
    data: { email: user.email, password: user.password },
  })
  const { access_token, refresh_token } = await res.json()
  await page.goto('/')
  await page.evaluate(({ at, rt }) => {
    localStorage.setItem('access_token', at)
    localStorage.setItem('refresh_token', rt)
  }, { at: access_token, rt: refresh_token })
  await page.goto('/fleet')
  await page.waitForSelector('h1:has-text("Fleet Dashboard")', { timeout: 8000 })
}
