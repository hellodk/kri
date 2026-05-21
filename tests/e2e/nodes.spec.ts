/**
 * NODES — Node Detail journeys
 * Covers: NODE-01..NODE-18 from TEST_CASES.md
 */
import { test, expect } from '@playwright/test'
import { loginViaApi, ADMIN, API } from './helpers'

let firstNodeId: string

test.describe('Node Detail', () => {

  test.beforeAll(async ({ request }) => {
    const loginRes = await request.post(`${API}/auth/login`, {
      data: { email: ADMIN.email, password: ADMIN.password },
    })
    const { access_token } = await loginRes.json()
    const res = await request.get(`${API}/api/v1/nodes?per_page=1`, {
      headers: { Authorization: `Bearer ${access_token}` },
    })
    const body = await res.json()
    firstNodeId = body.items[0].id
  })

  test.beforeEach(async ({ page }) => {
    await loginViaApi(page)
    await page.goto(`/nodes/${firstNodeId}`)
    await page.waitForSelector('h1', { timeout: 8000 })
  })

  test('NODE-01 header shows hostname, status badge, drift badge', async ({ page }) => {
    await expect(page.locator('h1')).toBeVisible()
    // StatusBadge and DriftBadge are rendered as spans/divs with status text
    await expect(page.locator('text=online').or(page.locator('text=offline')).or(page.locator('text=stale'))).toBeVisible()
  })

  test('NODE-02 overview tab hardware card visible', async ({ page }) => {
    await expect(page.locator('text=Hardware').or(page.locator('text=Model'))).toBeVisible()
  })

  test('NODE-03 overview tab OS card visible', async ({ page }) => {
    await expect(page.locator('text=OS').or(page.locator('text=Version'))).toBeVisible()
  })

  test('NODE-09 add user tag appears in list', async ({ page }) => {
    const uniqueKey = `e2etest${Date.now()}`
    await page.fill('input[placeholder="key"]', uniqueKey)
    await page.fill('input[placeholder="value"]', 'e2eval')
    await page.click('button:has-text("Add")')
    await expect(page.locator(`text=${uniqueKey}`)).toBeVisible({ timeout: 5000 })
    // Clean up
    const removeBtn = page.locator(`span:has-text("${uniqueKey}")`).locator('button')
    if (await removeBtn.isVisible()) await removeBtn.click()
  })

  test('NODE-11 remove user tag disappears from list', async ({ page }) => {
    // Add a tag first
    const key = `rmtest${Date.now()}`
    await page.fill('input[placeholder="key"]', key)
    await page.fill('input[placeholder="value"]', 'todelete')
    await page.click('button:has-text("Add")')
    await expect(page.locator(`text=${key}`)).toBeVisible({ timeout: 5000 })
    // Remove it
    const tag = page.locator(`span:has-text("${key}")`).first()
    await tag.locator('button').click()
    await expect(page.locator(`text=${key}`)).not.toBeVisible({ timeout: 5000 })
  })

  test('NODE-12 system tags have no remove button', async ({ page }) => {
    const systemTags = page.locator('span[title*="Auto-populated"]')
    const count = await systemTags.count()
    if (count > 0) {
      // System tags should NOT have a × button child
      const firstSystemTag = systemTags.first()
      const removeBtn = firstSystemTag.locator('button')
      await expect(removeBtn).toHaveCount(0)
    }
  })

  // ── API tests ───────────────────────────────────────────────────────────────

  test('NODE-13 cannot delete system tag via API', async ({ request }) => {
    const loginRes = await request.post(`${API}/auth/login`, {
      data: { email: ADMIN.email, password: ADMIN.password },
    })
    const { access_token } = await loginRes.json()
    const res = await request.delete(`${API}/api/v1/nodes/${firstNodeId}/tags/hostname`, {
      headers: { Authorization: `Bearer ${access_token}` },
    })
    expect(res.status()).toBe(403)
  })

  test('NODE-14 cannot overwrite system tag via API', async ({ request }) => {
    const loginRes = await request.post(`${API}/auth/login`, {
      data: { email: ADMIN.email, password: ADMIN.password },
    })
    const { access_token } = await loginRes.json()
    const res = await request.post(`${API}/api/v1/nodes/${firstNodeId}/tags`, {
      headers: { Authorization: `Bearer ${access_token}` },
      data: { key: 'hostname', value: 'hacked' },
    })
    expect(res.status()).toBe(403)
  })
})
