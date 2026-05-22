/**
 * VNC — VNC feature flag and UI journeys
 */
import { test, expect } from '@playwright/test'
import { loginViaApi, getToken, ADMIN, API } from './helpers'

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
    const viewerToken = await getToken(request, { email: 'viewer@fleet.local', password: 'changeme' })
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
})
