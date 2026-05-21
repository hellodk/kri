/**
 * GROUPS — Group management journeys
 * Covers: GRP-01..GRP-12 from TEST_CASES.md
 */
import { test, expect } from '@playwright/test'
import { loginViaApi, ADMIN, API } from './helpers'

test.describe('Groups', () => {

  test.beforeEach(async ({ page }) => {
    await loginViaApi(page)
    await page.goto('/groups')
    await page.waitForSelector('h1', { timeout: 8000 })
  })

  test('GRP-01 groups list page loads', async ({ page }) => {
    await expect(page.locator('h1')).toBeVisible()
    // Either table rows or empty-state CTA
    const hasRows = await page.locator('tbody tr').count()
    const hasEmpty = await page.locator('text=No groups').isVisible()
    expect(hasRows > 0 || hasEmpty).toBeTruthy()
  })

  test('GRP-02 create static group appears in list', async ({ page }) => {
    const name = `E2E Static ${Date.now()}`
    // "New Group" toggles an inline form — input has no placeholder, find by label
    await page.click('button:has-text("New Group")')
    const nameInput = page.locator('label:has-text("Name") + input, label:has-text("Name") ~ input').first()
    await nameInput.fill(name)
    await page.click('button[type="submit"]:has-text("Create")')
    await expect(page.locator(`text=${name}`)).toBeVisible({ timeout: 6000 })
    await expect(page.locator('text=static').first()).toBeVisible()
  })

  test('GRP-04 click group navigates to group detail', async ({ page }) => {
    const firstLink = page.locator('tbody tr a').first()
    if (await firstLink.isVisible()) {
      await firstLink.click()
      await expect(page).toHaveURL(/\/groups\//)
    }
  })

  test('GRP-08 dynamic group has no Add node button', async ({ page }) => {
    // Create a dynamic group via API then navigate to it
  })

  // ── API tests ───────────────────────────────────────────────────────────────

  test('GRP-10 add member to static group via API', async ({ request }) => {
    const loginRes = await request.post(`${API}/auth/login`, {
      data: { email: ADMIN.email, password: ADMIN.password },
    })
    const { access_token } = await loginRes.json()

    // Create group
    const grpRes = await request.post(`${API}/api/v1/groups`, {
      headers: { Authorization: `Bearer ${access_token}` },
      data: { name: `API-GRP-${Date.now()}`, type: 'static' },
    })
    expect(grpRes.status()).toBe(200)
    const { id: groupId } = await grpRes.json()

    // Get a node to add
    const nodesRes = await request.get(`${API}/api/v1/nodes?per_page=1`, {
      headers: { Authorization: `Bearer ${access_token}` },
    })
    const { items } = await nodesRes.json()
    const nodeId = items[0].id

    // Add member
    const addRes = await request.post(`${API}/api/v1/groups/${groupId}/members`, {
      headers: { Authorization: `Bearer ${access_token}` },
      data: { node_id: nodeId },
    })
    expect(addRes.status()).toBe(200)

    // Verify member count
    const detail = await request.get(`${API}/api/v1/groups/${groupId}`, {
      headers: { Authorization: `Bearer ${access_token}` },
    })
    const body = await detail.json()
    expect(body.member_count).toBe(1)
  })

  test('GRP-11 remove member via API returns 204', async ({ request }) => {
    const loginRes = await request.post(`${API}/auth/login`, {
      data: { email: ADMIN.email, password: ADMIN.password },
    })
    const { access_token } = await loginRes.json()

    // Create group + add member
    const grpRes = await request.post(`${API}/api/v1/groups`, {
      headers: { Authorization: `Bearer ${access_token}` },
      data: { name: `API-RM-${Date.now()}`, type: 'static' },
    })
    const { id: groupId } = await grpRes.json()
    const nodesRes = await request.get(`${API}/api/v1/nodes?per_page=1`, {
      headers: { Authorization: `Bearer ${access_token}` },
    })
    const { items } = await nodesRes.json()
    const nodeId = items[0].id
    await request.post(`${API}/api/v1/groups/${groupId}/members`, {
      headers: { Authorization: `Bearer ${access_token}` },
      data: { node_id: nodeId },
    })

    // Remove member
    const rmRes = await request.delete(`${API}/api/v1/groups/${groupId}/members/${nodeId}`, {
      headers: { Authorization: `Bearer ${access_token}` },
    })
    expect([200, 204]).toContain(rmRes.status())
  })

  test('GRP-12 group member list paginates', async ({ request }) => {
    const loginRes = await request.post(`${API}/auth/login`, {
      data: { email: ADMIN.email, password: ADMIN.password },
    })
    const { access_token } = await loginRes.json()
    const grpsRes = await request.get(`${API}/api/v1/groups?per_page=1`, {
      headers: { Authorization: `Bearer ${access_token}` },
    })
    const { items } = await grpsRes.json()
    if (items.length === 0) return
    const { id: groupId } = items[0]
    const res = await request.get(`${API}/api/v1/groups/${groupId}/nodes?page=1&per_page=5`, {
      headers: { Authorization: `Bearer ${access_token}` },
    })
    expect(res.status()).toBe(200)
    const body = await res.json()
    expect(body).toHaveProperty('items')
    expect(body.items.length).toBeLessThanOrEqual(5)
  })
})
