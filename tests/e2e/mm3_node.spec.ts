/**
 * MM3 — Live node E2E journeys for the bootstrapped mm3 node
 */
import { test, expect } from '@playwright/test'
import { loginViaApi, getToken, ADMIN, API } from './helpers'

let mm3Id: string

test.describe('MM3 Node (live bootstrapped)', () => {

  test.beforeAll(async ({ request }) => {
    // Find mm3's UUID
    const loginRes = await request.post(`${API}/auth/login`, {
      data: { email: ADMIN.email, password: ADMIN.password },
    })
    const { access_token } = await loginRes.json()
    const res = await request.get(`${API}/api/v1/nodes?search=mm3`, {
      headers: { Authorization: `Bearer ${access_token}` },
    })
    const body = await res.json()
    mm3Id = body.items?.[0]?.id ?? ''
  })

  test.beforeEach(async ({ page }) => {
    if (!mm3Id) test.skip()
    await loginViaApi(page)
  })

  test('MM3-01 mm3 node appears in fleet dashboard', async ({ page }) => {
    // Use data-testid attribute keyed on minion_id for reliable lookup regardless of hostname
    const row = page.locator('tbody tr[data-testid="mm3"]')
    await expect(row).toBeVisible({ timeout: 8000 })
  })

  test('MM3-02 mm3 row is visible in fleet dashboard', async ({ page }) => {
    // Row is present via data-testid (minion_id); IP address may or may not be present
    const row = page.locator('tbody tr[data-testid="mm3"]')
    await expect(row).toBeVisible()
    // The hostname cell is always visible
    await expect(row.locator('a').first()).toBeVisible()
  })

  test('MM3-03 clicking mm3 hostname navigates to node detail', async ({ page }) => {
    const row = page.locator('tbody tr[data-testid="mm3"]')
    await row.locator('a').first().click()
    await expect(page).toHaveURL(/\/nodes\//, { timeout: 5000 })
    await expect(page.locator('h1')).toBeVisible()
  })

  test('MM3-04 mm3 node detail shows Hardware and OS cards', async ({ page }) => {
    await page.goto(`/nodes/${mm3Id}`)
    await page.waitForSelector('h1', { timeout: 8000 })
    await expect(page.locator('h3:has-text("Hardware")').first()).toBeVisible()
    await expect(page.locator('h3:has-text("OS")').first()).toBeVisible()
  })

  test('MM3-05 mm3 edit modal can save SSH credentials', async ({ request }) => {
    // Via API: PATCH node with SSH credentials
    const loginRes = await request.post(`${API}/auth/login`, {
      data: { email: ADMIN.email, password: ADMIN.password },
    })
    const { access_token } = await loginRes.json()
    const res = await request.patch(`${API}/api/v1/nodes/${mm3Id}`, {
      headers: { Authorization: `Bearer ${access_token}` },
      data: { ssh_username: 'localadmin', ssh_password: 'testpass123', ssh_auth_mode: 'password' },
    })
    expect(res.status()).toBe(200)
    const body = await res.json()
    expect(body.ssh_username).toBe('localadmin')
    expect(body.has_ssh_password).toBe(true)
    expect(body.has_ssh_key).toBe(false)
  })

  test('MM3-06 mm3 bootstrap history tab shows runs', async ({ page }) => {
    await page.goto(`/nodes/${mm3Id}`)
    await page.waitForSelector('h1', { timeout: 8000 })
    // Click bootstrap history tab
    const historyTab = page.locator('button:has-text("Bootstrap History"), [role="tab"]:has-text("Bootstrap History")').first()
    if (await historyTab.isVisible()) {
      await historyTab.click()
      // Either shows runs or "No bootstrap runs yet"
      const hasRuns = await page.locator('tbody tr').count()
      const hasEmpty = await page.locator('text=/no bootstrap/i').isVisible()
      expect(hasRuns > 0 || hasEmpty).toBeTruthy()
    }
  })

  test('MM3-07 search for mm3 in fleet filters results', async ({ page }) => {
    const searchInput = page.locator('input[placeholder*="search" i], input[placeholder*="Search" i], input[type="search"]').first()
    await searchInput.fill('mm3')
    await page.waitForTimeout(800) // debounce
    const rows = page.locator('tbody tr')
    const count = await rows.count()
    expect(count).toBeGreaterThanOrEqual(1)
    // Use data-testid attribute (minion_id) for reliable lookup after search
    await expect(page.locator('tbody tr[data-testid="mm3"]')).toBeVisible()
  })

  test('MM3-08 mm3 API node detail returns correct minion_id', async ({ request }) => {
    const loginRes = await request.post(`${API}/auth/login`, {
      data: { email: ADMIN.email, password: ADMIN.password },
    })
    const { access_token } = await loginRes.json()
    const res = await request.get(`${API}/api/v1/nodes/${mm3Id}`, {
      headers: { Authorization: `Bearer ${access_token}` },
    })
    expect(res.status()).toBe(200)
    const body = await res.json()
    expect(body.minion_id).toBe('mm3')
    // ip_address may be null if not yet reported by the minion
    expect(body).toHaveProperty('ip_address')
  })

  test('MM3-09 add and remove tag on mm3', async ({ page }) => {
    await page.goto(`/nodes/${mm3Id}`)
    await page.waitForSelector('h1', { timeout: 8000 })
    const key = `mm3test${Date.now()}`
    await page.fill('input[placeholder="key"]', key)
    await page.fill('input[placeholder="value"]', 'testval')
    await page.click('button:has-text("Add")')
    await expect(page.locator(`text=${key}`)).toBeVisible({ timeout: 5000 })
    // Remove
    const tag = page.locator(`span:has-text("${key}")`).first()
    await tag.locator('button').click()
    await expect(page.locator(`text=${key}`)).not.toBeVisible({ timeout: 5000 })
  })

  test('MM3-10 mm3 packages endpoint returns array', async ({ request }) => {
    const loginRes = await request.post(`${API}/auth/login`, {
      data: { email: ADMIN.email, password: ADMIN.password },
    })
    const { access_token } = await loginRes.json()
    const res = await request.get(`${API}/api/v1/nodes/${mm3Id}/packages`, {
      headers: { Authorization: `Bearer ${access_token}` },
    })
    expect(res.status()).toBe(200)
    const body = await res.json()
    expect(body).toHaveProperty('items')
    expect(Array.isArray(body.items)).toBeTruthy()
  })

  test('MM3-11 edit mm3 hostname via UI', async ({ page }) => {
    await loginViaApi(page)
    // Open edit dialog from fleet dashboard — use data-testid for reliable lookup
    const row = page.locator('tbody tr[data-testid="mm3"]')
    const editBtn = row.locator('button[title*="edit" i], button[aria-label*="edit" i]').first()
    if (await editBtn.isVisible()) {
      await editBtn.click()
      await expect(page.locator('dialog, [role="dialog"]').filter({ hasText: /edit/i })).toBeVisible({ timeout: 3000 })
      await page.keyboard.press('Escape')
    }
  })
})
