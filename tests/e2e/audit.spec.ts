/**
 * AUDIT — Audit log journeys
 */
import { test, expect } from '@playwright/test'
import { loginViaApi, getToken, ADMIN, VIEWER, API } from './helpers'

test.describe('Audit Log', () => {

  test.beforeEach(async ({ page }) => {
    test.setTimeout(90000)
    await loginViaApi(page)
    await page.goto('/audit')
    await page.waitForSelector('h1', { timeout: 8000 })
  })

  test('AUDIT-01 audit page loads', async ({ page }) => {
    await expect(page.locator('h1')).toBeVisible()
  })

  test('AUDIT-02 audit table shows entries or no-events message', async ({ page }) => {
    // After all the operations we have done, audit events or empty state should be visible
    // Wait for either the table or the empty state text
    const table = page.locator('table').first()
    const noEvents = page.locator('text=No audit events found')
    await expect(table.or(noEvents).first()).toBeVisible({ timeout: 8000 })
  })

  test('AUDIT-03 API returns paginated audit logs', async ({ request }) => {
    const token = await getToken(request)
    const res = await request.get(`${API}/api/v1/audit?per_page=10`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    expect(res.status()).toBe(200)
    const body = await res.json()
    expect(body).toHaveProperty('items')
    expect(body).toHaveProperty('total')
    expect(Array.isArray(body.items)).toBeTruthy()
  })

  test('AUDIT-04 API filters by action', async ({ request }) => {
    const token = await getToken(request)
    const res = await request.get(`${API}/api/v1/audit?action=auth.login&per_page=5`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    expect(res.status()).toBe(200)
    const body = await res.json()
    for (const item of body.items) {
      expect(item.action).toContain('auth.login')
    }
  })

  test('AUDIT-05 viewer is forbidden from reading the audit log', async ({ request }) => {
    // The audit list endpoint requires admin or auditor (require_role("admin",
    // "auditor") in routes/audit.py); a viewer is intentionally forbidden. The
    // old assertion expected 200, which never matched the product RBAC (#905).
    const viewerToken = await getToken(request, VIEWER)
    const res = await request.get(`${API}/api/v1/audit`, {
      headers: { Authorization: `Bearer ${viewerToken}` },
    })
    expect(res.status()).toBe(403)
  })
})
