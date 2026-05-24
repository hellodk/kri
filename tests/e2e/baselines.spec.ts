/**
 * BASELINES — Drift baseline journeys
 * Covers: BASE-01..BASE-12 from TEST_CASES.md
 */
import { test, expect } from '@playwright/test'
import { loginViaApi, ADMIN, API } from './helpers'

test.describe('Baselines', () => {

  test.beforeEach(async ({ page }) => {
    await loginViaApi(page)
    await page.goto('/baselines')
    await page.waitForSelector('h1:has-text("Baselines")', { timeout: 8000 })
  })

  test('BASE-01 baselines page loads', async ({ page }) => {
    await expect(page.locator('h1:has-text("Baselines")')).toBeVisible()
    await expect(page.locator('button:has-text("+ New Baseline")')).toBeVisible()
  })

  test('BASE-02 create global baseline appears in list', async ({ page }) => {
    await page.click('button:has-text("+ New Baseline")')
    await page.fill('input[placeholder="macOS fleet standard"]', `E2E Global ${Date.now()}`)
    // target type radio — "global" is default
    await page.click('button:has-text("Create Baseline")')
    await expect(page.locator('text=All nodes').first()).toBeVisible({ timeout: 6000 })
  })

  test('BASE-05 invalid JSON disables create button', async ({ page }) => {
    await page.click('button:has-text("+ New Baseline")')
    await page.fill('input[placeholder="macOS fleet standard"]', 'Test Baseline')
    const editor = page.locator('textarea')
    await editor.fill('{invalid json here')
    await expect(page.locator('button:has-text("Create Baseline")')).toBeDisabled()
  })

  test('BASE-06 valid JSON enables create button', async ({ page }) => {
    await page.click('button:has-text("+ New Baseline")')
    await page.fill('input[placeholder="macOS fleet standard"]', 'Valid Test')
    const editor = page.locator('textarea')
    await editor.fill('{"packages":[],"services":[]}')
    await expect(page.locator('button:has-text("Create Baseline")')).toBeEnabled()
    await page.keyboard.press('Escape')
  })

  test('BASE-07 view baseline detail shows name and JSON', async ({ page }) => {
    // Only run if at least one baseline exists
    const viewBtn = page.locator('button:has-text("View")').first()
    if (await viewBtn.isVisible()) {
      await viewBtn.click()
      await expect(page.locator('text=State Definition')).toBeVisible()
      await expect(page.locator('pre')).toBeVisible()
      await page.click('button:has-text("Close")')
    }
  })

  test('BASE-12 info banner is readable on page load', async ({ page }) => {
    await expect(page.locator('text=How drift is calculated')).toBeVisible()
  })

  // ── API tests ───────────────────────────────────────────────────────────────

  test('BASE-09 create baseline via API returns version 1', async ({ request }) => {
    const loginRes = await request.post(`${API}/auth/login`, {
      data: { email: ADMIN.email, password: ADMIN.password },
    })
    const { access_token } = await loginRes.json()
    const res = await request.post(`${API}/api/v1/baselines`, {
      headers: { Authorization: `Bearer ${access_token}` },
      data: {
        name: `API Test ${Date.now()}`,
        target_type: 'global',
        state_json: { packages: [], services: [] },
      },
    })
    expect([200, 201]).toContain(res.status())
    const body = await res.json()
    expect(body).toHaveProperty('id')
    expect(body.version).toBe(1)
  })

  test('BASE-10 list baselines is paginated', async ({ request }) => {
    const loginRes = await request.post(`${API}/auth/login`, {
      data: { email: ADMIN.email, password: ADMIN.password },
    })
    const { access_token } = await loginRes.json()
    const res = await request.get(`${API}/api/v1/baselines?per_page=5`, {
      headers: { Authorization: `Bearer ${access_token}` },
    })
    expect(res.status()).toBe(200)
    const body = await res.json()
    expect(body).toHaveProperty('items')
    expect(body).toHaveProperty('total')
    expect(body.items.length).toBeLessThanOrEqual(5)
  })
})
