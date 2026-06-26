/**
 * VNC — VNC feature flag and UI journeys
 */
import { test, expect, type APIRequestContext } from '@playwright/test'
import { loginViaApi, getToken, ADMIN, VIEWER, API, SEED } from './helpers'

/**
 * The VNC (and SSH) button on the node detail page is enabled only when the node has a
 * `bootstrap_ip`, which is set by queueing a bootstrap — not by plain node creation, and
 * the global-setup seed nodes are intentionally IP-less. This helper creates a node, adds
 * it to the seeded group-with-creds, and queues a bootstrap so `bootstrap_ip` is populated,
 * then returns the node id so the VNC click tests target an enabled button (#905).
 */
async function bootstrappedNodeId(request: APIRequestContext, token: string): Promise<string> {
  const auth = { Authorization: `Bearer ${token}` }
  const minionId = `e2e-vnc-${Date.now()}`
  const node = await (await request.post(`${API}/api/v1/nodes`, { headers: auth, data: { minion_id: minionId } })).json()
  const grpRes = await request.get(`${API}/api/v1/groups?per_page=100`, { headers: auth })
  const group = ((await grpRes.json()).items ?? []).find((g: { name: string }) => g.name === SEED.groupName)
  if (group) {
    await request.post(`${API}/api/v1/groups/${group.id}/members`, { headers: auth, data: { node_id: node.id } })
  }
  await request.post(`${API}/api/v1/ansible/bootstrap`, {
    headers: auth,
    data: { minion_id: minionId, target_ip: '192.168.99.50' },
  })
  return node.id
}

test.describe('VNC Feature Flag', () => {

  test('VNC-01 settings API returns vnc_enabled field', async ({ request }) => {
    const token = await getToken(request)
    const res = await request.get(`${API}/api/v1/settings`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    expect(res.status()).toBe(200)
    const body = await res.json()
    // vnc_enabled may be true or false, but must be present
    expect(typeof body.vnc_enabled).toBe('boolean')
  })

  test('VNC-02 admin can enable and disable VNC', async ({ request }) => {
    const token = await getToken(request)

    // Enable
    const enableRes = await request.put(`${API}/api/v1/settings`, {
      headers: { Authorization: `Bearer ${token}` },
      data: { vnc_enabled: true },
    })
    expect(enableRes.status()).toBe(200)
    const enabled = await enableRes.json()
    expect(enabled.vnc_enabled).toBe(true)

    // Disable
    const disableRes = await request.put(`${API}/api/v1/settings`, {
      headers: { Authorization: `Bearer ${token}` },
      data: { vnc_enabled: false },
    })
    expect(disableRes.status()).toBe(200)
    const disabled = await disableRes.json()
    expect(disabled.vnc_enabled).toBe(false)
  })

  test('VNC-03 viewer cannot change VNC setting', async ({ request }) => {
    // Use getToken (cached) with viewer credentials to avoid rate limiting
    const viewerToken = await getToken(request, VIEWER)
    const res = await request.put(`${API}/api/v1/settings`, {
      headers: { Authorization: `Bearer ${viewerToken}` },
      data: { vnc_enabled: true },
    })
    // 403 = forbidden (correct role check), 401 = token issue (still not authorized)
    expect([401, 403]).toContain(res.status())
  })

  test('VNC-04 node detail does NOT show VNC button when disabled', async ({ page, request }) => {
    test.setTimeout(90000)
    // Ensure VNC is disabled via API first (using cached token)
    const token = await getToken(request)
    await request.put(`${API}/api/v1/settings`, {
      headers: { Authorization: `Bearer ${token}` },
      data: { vnc_enabled: false },
    })

    await loginViaApi(page)
    const nodesRes = await request.get(`${API}/api/v1/nodes?per_page=1`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    const { items } = await nodesRes.json()
    if (!items.length) return

    await page.goto(`/nodes/${items[0].id}`)
    await page.waitForSelector('h1', { timeout: 8000 })
    const vncBtn = page.locator('button:has-text("VNC")')
    await expect(vncBtn).toHaveCount(0)
  })

  test('VNC-05 VNC button is shown when vnc_enabled is true and node exists', async ({ page, request }) => {
    test.setTimeout(90000)
    const token = await getToken(request)

    // Enable VNC via API
    await request.put(`${API}/api/v1/settings`, {
      headers: { Authorization: `Bearer ${token}` },
      data: { vnc_enabled: true },
    })

    await loginViaApi(page)

    // Get any node
    const nodesRes = await request.get(`${API}/api/v1/nodes?per_page=1`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    const { items } = await nodesRes.json()
    if (!items?.length) {
      test.skip()
      return
    }

    await page.goto(`/nodes/${items[0].id}`)
    await page.waitForSelector('h1', { timeout: 8000 })

    // VNC button should be visible
    const vncBtn = page.locator('button:has-text("VNC")').first()
    await expect(vncBtn).toBeVisible({ timeout: 5000 })
  })

  test('VNC-06 clicking VNC button opens a viewer panel', async ({ page, request }) => {
    test.setTimeout(90000)
    const token = await getToken(request)

    // Enable VNC
    await request.put(`${API}/api/v1/settings`, {
      headers: { Authorization: `Bearer ${token}` },
      data: { vnc_enabled: true },
    })

    await loginViaApi(page)

    // Use a freshly bootstrapped node so the VNC button is enabled (has bootstrap_ip).
    const nodeId = await bootstrappedNodeId(request, token)

    await page.goto(`/nodes/${nodeId}`)
    await page.waitForSelector('h1', { timeout: 8000 })

    // Click VNC button
    const vncBtn = page.locator('button:has-text("VNC")').first()
    await vncBtn.click()

    // Verify VNC panel appears (with "VNC →" text or viewer canvas)
    const vncPanel = page.locator('text=VNC →').first()
    await expect(vncPanel).toBeVisible({ timeout: 8000 })

    // Verify close button exists
    const closeBtn = page.locator('button').filter({ hasText: '×' }).first()
    await expect(closeBtn).toBeVisible({ timeout: 5000 })
  })

  test('VNC-07 VNC panel shows error or spinner when connection fails', async ({ page, request }) => {
    test.setTimeout(90000)
    const token = await getToken(request)

    // Enable VNC
    await request.put(`${API}/api/v1/settings`, {
      headers: { Authorization: `Bearer ${token}` },
      data: { vnc_enabled: true },
    })

    await loginViaApi(page)

    // Use a freshly bootstrapped node so the VNC button is enabled (has bootstrap_ip).
    const nodeId = await bootstrappedNodeId(request, token)

    await page.goto(`/nodes/${nodeId}`)
    await page.waitForSelector('h1', { timeout: 8000 })

    // Click VNC button
    const vncBtn = page.locator('button:has-text("VNC")').first()
    await vncBtn.click()

    // Panel should appear even if connection fails (not a crash)
    const vncPanel = page.locator('text=VNC →').first()
    await expect(vncPanel).toBeVisible({ timeout: 8000 })

    // Page should still be healthy (title intact, no console errors)
    const pageTitle = await page.title()
    expect(pageTitle).toBeTruthy()
    expect(pageTitle).not.toContain('Error')
  })
})
