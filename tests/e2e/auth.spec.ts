/**
 * AUTH — Authentication journeys
 * Covers: AUTH-01..AUTH-09 from TEST_CASES.md
 */
import { test, expect, request } from '@playwright/test'
import { ADMIN, API } from './helpers'

test.describe('Authentication', () => {

  // ── Browser / UI tests ─────────────────────────────────────────────────────

  test('AUTH-01 login with valid credentials redirects to fleet', async ({ page }) => {
    await page.goto('/login')
    await page.fill('input[type="email"]', ADMIN.email)
    await page.fill('input[type="password"]', ADMIN.password)
    await page.click('button[type="submit"]')
    await expect(page).toHaveURL(/\/fleet/, { timeout: 8000 })
    await expect(page.locator('h1:has-text("Fleet Dashboard")')).toBeVisible()
  })

  test('AUTH-02 wrong password shows error, stays on login', async ({ page }) => {
    await page.goto('/login')
    await page.fill('input[type="email"]', ADMIN.email)
    await page.fill('input[type="password"]', 'wrong-password')
    await page.click('button[type="submit"]')
    await expect(page).toHaveURL(/\/login/)
    await expect(page.locator('[role="alert"]')).toBeVisible({ timeout: 6000 })
  })

  test('AUTH-03 unknown email shows error', async ({ page }) => {
    await page.goto('/login')
    await page.fill('input[type="email"]', 'nobody@unknown.tld')
    await page.fill('input[type="password"]', 'anything')
    await page.click('button[type="submit"]')
    await expect(page).toHaveURL(/\/login/)
    await expect(page.locator('[role="alert"]')).toBeVisible({ timeout: 6000 })
  })

  test('AUTH-09 protected route without session redirects to login', async ({ page }) => {
    // Navigate directly without logging in
    await page.goto('/fleet')
    await expect(page).toHaveURL(/\/login/, { timeout: 5000 })
  })

  // ── API tests (no browser overhead) ────────────────────────────────────────

  test('AUTH-04 login API returns JWT triple', async ({ request }) => {
    const res = await request.post(`${API}/auth/login`, {
      data: { email: ADMIN.email, password: ADMIN.password },
    })
    expect(res.status()).toBe(200)
    const body = await res.json()
    expect(body).toHaveProperty('access_token')
    expect(body).toHaveProperty('refresh_token')
    expect(body.token_type).toBe('bearer')
  })

  test('AUTH-05 protected API endpoint rejects missing token', async ({ request }) => {
    const res = await request.get(`${API}/api/v1/nodes`)
    expect(res.status()).toBe(401)
  })

  test('AUTH-06 refresh token rotates the pair', async ({ request }) => {
    const loginRes = await request.post(`${API}/auth/login`, {
      data: { email: ADMIN.email, password: ADMIN.password },
    })
    const { refresh_token } = await loginRes.json()
    const refreshRes = await request.post(`${API}/auth/refresh`, {
      data: { refresh_token },
    })
    expect(refreshRes.status()).toBe(200)
    const refreshed = await refreshRes.json()
    expect(refreshed).toHaveProperty('access_token')
    expect(refreshed.refresh_token).not.toBe(refresh_token)
  })

  test('AUTH-07 logout revokes refresh token', async ({ request }) => {
    const loginRes = await request.post(`${API}/auth/login`, {
      data: { email: ADMIN.email, password: ADMIN.password },
    })
    const { access_token, refresh_token } = await loginRes.json()
    await request.post(`${API}/auth/logout`, {
      headers: { Authorization: `Bearer ${access_token}` },
      data: { refresh_token },
    })
    const afterLogout = await request.post(`${API}/auth/refresh`, {
      data: { refresh_token },
    })
    expect(afterLogout.status()).toBe(401)
  })
})
