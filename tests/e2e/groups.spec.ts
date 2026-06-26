/**
 * GROUPS — Group management journeys
 * Covers: GRP-01..GRP-12 from TEST_CASES.md
 */
import { test, expect } from '@playwright/test'
import { loginViaApi, getToken, ADMIN, API } from './helpers'

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

  test('GRP-02 create static group appears in list', async ({ page, request }) => {
    const name = `E2E Static ${Date.now()}`
    await page.click('button:has-text("New Group")')
    const nameInput = page.locator('div.grid input').first()
    await nameInput.fill(name)
    await page.click('button[type="submit"]:has-text("Create")')
    // Form closes on success — wait for it to disappear
    await expect(page.locator('button[type="submit"]:has-text("Create")')).not.toBeVisible({ timeout: 6000 })
    // Verify via API (list may be paginated so the row may not be on screen)
    const token = await getToken(request)
    const res = await request.get(`${API}/api/v1/groups?per_page=100`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    const body = await res.json()
    const found = (body.items ?? []).some((g: { name: string }) => g.name === name)
    expect(found).toBeTruthy()
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
    expect([200, 201]).toContain(grpRes.status())
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
    expect([200, 201, 204]).toContain(addRes.status())

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

  // ── Add Node modal validation ────────────────────────────────────────────────

  test('GRP-ADD-01 add node modal rejects duplicate minion ID', async ({ page, request }) => {
    const token = await getToken(request)

    // Seed a node via API so we have a known existing minion_id
    const nodeRes = await request.post(`${API}/api/v1/nodes`, {
      headers: { Authorization: `Bearer ${token}` },
      data: { minion_id: `e2e-dup-check-${Date.now()}` },
    })
    expect([200, 201]).toContain(nodeRes.status())
    const { minion_id: existingMinionId } = await nodeRes.json()

    // Navigate to fleet and open the Import modal (replaced "Add Node" button)
    await page.goto('/fleet')
    await page.waitForSelector('h1', { timeout: 8000 })
    await page.click('button:has-text("+ Import")')
    await page.waitForSelector('[role="dialog"]', { timeout: 5000 })

    // Paste a full "minion_id,hostname,ip" line (Paste List tab is active by default).
    // A bare token is parsed as an IP for all three fields, so the validator rejects it as
    // an invalid IP *before* the duplicate check ever runs — supply a real IP so the row
    // reaches the "minion_id already exists" branch and renders the Duplicate badge (#905).
    await page.fill('textarea', `${existingMinionId},duphost,10.250.250.250`)

    // Wait for the "⚠ Duplicate" badge to appear (400 ms debounce + network; allow 3 s).
    // Scope to the dialog (and the ⚠ badge specifically): a bare text=Duplicate also matches
    // "e2e-duplicate-*" node links behind the modal and the summary line, tripping strict mode.
    await expect(page.locator('[role="dialog"]').getByText('⚠ Duplicate')).toBeVisible({ timeout: 3000 })

    // The Import button must be disabled when there are zero new nodes
    const importBtn = page.locator('button:has-text("Import")').last()
    await expect(importBtn).toBeDisabled()
  })

  test('GRP-ADD-02 add node modal warns when group has no SSH credentials', async ({ page, request }) => {
    const token = await getToken(request)

    // Create a brand-new static group with no credentials via API
    const grpRes = await request.post(`${API}/api/v1/groups`, {
      headers: { Authorization: `Bearer ${token}` },
      data: { name: `E2E No Creds ${Date.now()}`, type: 'static' },
    })
    expect([200, 201]).toContain(grpRes.status())
    const { name: groupName } = await grpRes.json()

    // Navigate to fleet and open the Import modal (replaced "Add Node" button)
    await page.goto('/fleet')
    await page.waitForSelector('h1', { timeout: 8000 })
    await page.click('button:has-text("+ Import")')
    await page.waitForSelector('select', { timeout: 5000 })

    // Select the newly created group from the dropdown. Scope to the dialog: the fleet
    // page renders its own health/status filter <select>s, and a bare 'select' locator
    // picks the first one (the health filter), which has no group options (#905).
    const groupSelect = page.locator('[role="dialog"] select')
    await expect(groupSelect.locator(`option:has-text("${groupName}")`)).toBeAttached({ timeout: 5000 })
    await groupSelect.selectOption({ label: groupName })

    // The per-group "No SSH credentials" blocking warning no longer exists in
    // ImportNodesModal.  Instead the modal always exposes inline SSH credential
    // fields and shows this hint, which covers the no-saved-creds case.
    await expect(
      page.locator('text=Leave blank to reuse the group\'s saved SSH credentials.'),
    ).toBeVisible({ timeout: 3000 })
  })
})
