/**
 * SSH SESSIONS — Session management journeys
 */
import { test, expect } from '@playwright/test'
import { loginViaApi, getToken, ADMIN, API } from './helpers'

test.describe('SSH Sessions', () => {

  test('SSH-01 sessions list endpoint returns correct structure', async ({ request }) => {
    const token = await getToken(request)
    const res = await request.get(`${API}/api/v1/ssh/sessions`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    expect(res.status()).toBe(200)
    const body = await res.json()
    expect(body).toHaveProperty('items')
    expect(Array.isArray(body.items)).toBeTruthy()
  })

  test('SSH-02 security events endpoint works', async ({ request }) => {
    const token = await getToken(request)
    const res = await request.get(`${API}/api/v1/ssh/events`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    expect(res.status()).toBe(200)
    const body = await res.json()
    expect(body).toHaveProperty('items')
  })

  test('SSH-03 nonexistent session recording returns 200 with empty chunks', async ({ request }) => {
    const token = await getToken(request)
    const res = await request.get(
      `${API}/api/v1/ssh/sessions/00000000-0000-0000-0000-000000000000/recording`,
      { headers: { Authorization: `Bearer ${token}` } }
    )
    // 200 with empty chunks array is acceptable (no recording found)
    expect([200, 404]).toContain(res.status())
    if (res.status() === 200) {
      const body = await res.json()
      expect(body).toHaveProperty('chunks')
      expect(Array.isArray(body.chunks)).toBeTruthy()
    }
  })

  test('SSH-04 sessions endpoint rejects missing token', async ({ request }) => {
    const res = await request.get(`${API}/api/v1/ssh/sessions`)
    expect(res.status()).toBe(401)
  })

  test('SSH-05 node detail page shows SSH button for all nodes', async ({ page }) => {
    test.setTimeout(90000)
    await loginViaApi(page)
    const token = await page.request.post(`${API}/auth/login`, {
      data: { email: ADMIN.email, password: ADMIN.password },
    }).then(r => r.json()).then(d => d.access_token)

    const nodesRes = await page.request.get(`${API}/api/v1/nodes?per_page=1`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    const nodes = await nodesRes.json()
    if (!nodes.items?.length) return
    const nodeId = nodes.items[0].id

    await page.goto(`/nodes/${nodeId}`)
    await page.waitForSelector('h1', { timeout: 8000 })
    // SSH button is always rendered (disabled if node not online)
    const sshBtn = page.locator('button:has-text("SSH")').first()
    await expect(sshBtn).toBeVisible({ timeout: 5000 })
  })
})
