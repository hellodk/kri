/**
 * BASELINES — Drift baseline journeys
 * Covers: BASE-01..BASE-12 from TEST_CASES.md
 */
import { test, expect } from '@playwright/test'
import { loginViaApi, getToken, ADMIN, API } from './helpers'

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

  test('BASE-02 create global baseline appears in list', async ({ page, request }) => {
    const name = `E2E Global ${Date.now()}`
    await page.click('button:has-text("+ New Baseline")')
    // Modal opens in 'choose' mode — must pick a creation method before form fields render
    await page.click('button:has-text("Build manually")')
    // Placeholder changed from "macOS fleet standard" to "macOS production standard"
    await page.fill('input[placeholder="macOS production standard"]', name)
    // Add one required package so hasContent becomes true (Create button guard)
    await page.click('button:has-text("+ Add required package")')
    await page.locator('input[placeholder="package name"]').first().fill('bash')
    // global is the default target_type ("All nodes" radio pre-selected)
    await page.click('button:has-text("Create Baseline")')
    // Wait for modal to close (onSuccess calls onClose)
    await expect(page.locator('h2:has-text("Build Manually")')).toBeHidden({ timeout: 8000 })
    // Verify via API — list is paginated so newest item may not be on page 1
    const token = await getToken(request)
    const res = await request.get(`${API}/api/v1/baselines?per_page=100`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    expect(res.status()).toBe(200)
    const body = await res.json()
    const found = body.items.some(
      (b: { name: string; target_type: string }) => b.name === name && b.target_type === 'global'
    )
    expect(found).toBeTruthy()
  })

  test('BASE-05 no content disables create button', async ({ page }) => {
    await page.click('button:has-text("+ New Baseline")')
    // Must enter manual mode before form fields render
    await page.click('button:has-text("Build manually")')
    await page.fill('input[placeholder="macOS production standard"]', 'Test Baseline')
    // No packages or services added → hasContent is false → Create button stays disabled
    await expect(page.locator('button:has-text("Create Baseline")')).toBeDisabled()
  })

  test('BASE-06 filled package enables create button', async ({ page }) => {
    await page.click('button:has-text("+ New Baseline")')
    // Must enter manual mode before form fields render
    await page.click('button:has-text("Build manually")')
    await page.fill('input[placeholder="macOS production standard"]', 'Valid Test')
    // Add a package name so hasContent becomes true → Create button enabled
    await page.click('button:has-text("+ Add required package")')
    await page.locator('input[placeholder="package name"]').first().fill('bash')
    await expect(page.locator('button:has-text("Create Baseline")')).toBeEnabled()
    await page.click('button:has-text("Cancel")')
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
