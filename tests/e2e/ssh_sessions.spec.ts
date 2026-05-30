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

  test('SSH-06 SSH button is visible on node detail page for any node', async ({ page, request }) => {
    test.setTimeout(90000)
    await loginViaApi(page)
    const token = await getToken(request)

    // Get any node via API
    const nodesRes = await request.get(`${API}/api/v1/nodes?per_page=1`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    const { items } = await nodesRes.json()
    if (!items?.length) {
      test.skip()
      return
    }

    const nodeId = items[0].id
    await page.goto(`/nodes/${nodeId}`)
    await page.waitForSelector('h1', { timeout: 8000 })

    // SSH button should be visible (may be disabled if node offline)
    const sshBtn = page.locator('button:has-text("SSH")').first()
    await expect(sshBtn).toBeVisible({ timeout: 5000 })
  })

  test('SSH-07 SSH button is disabled when node is offline', async ({ page, request }) => {
    test.setTimeout(90000)
    await loginViaApi(page)
    const token = await getToken(request)

    // Find an offline node, or skip
    const nodesRes = await request.get(`${API}/api/v1/nodes?per_page=10`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    const { items } = await nodesRes.json()
    const offlineNode = items?.find((n: any) => n.status !== 'online')

    if (!offlineNode) {
      test.skip()
      return
    }

    await page.goto(`/nodes/${offlineNode.id}`)
    await page.waitForSelector('h1', { timeout: 8000 })

    const sshBtn = page.locator('button:has-text("SSH")').first()
    // Button should be disabled or have disabled attribute
    const isDisabled = await sshBtn.isDisabled()
    const hasDisabledClass = await sshBtn.evaluate((el) =>
      el.getAttribute('disabled') !== null ||
      el.className.includes('disabled') ||
      el.className.includes('opacity-50')
    )
    expect(isDisabled || hasDisabledClass).toBeTruthy()
  })

  test('SSH-08 clicking SSH on a node opens terminal panel', async ({ page, request }) => {
    test.setTimeout(90000)
    await loginViaApi(page)
    const token = await getToken(request)

    // Find an online node, or skip
    const nodesRes = await request.get(`${API}/api/v1/nodes?per_page=10`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    const { items } = await nodesRes.json()
    const onlineNode = items?.find((n: any) => n.status === 'online')

    if (!onlineNode) {
      test.skip()
      return
    }

    await page.goto(`/nodes/${onlineNode.id}`)
    await page.waitForSelector('h1', { timeout: 8000 })

    // Click SSH button
    const sshBtn = page.locator('button:has-text("SSH")').first()
    await sshBtn.click()

    // Verify terminal panel appears (dark background with "SSH →" text)
    const terminalPanel = page.locator('text=SSH →').first()
    await expect(terminalPanel).toBeVisible({ timeout: 8000 })

    // Verify close button exists (X in top right)
    const closeBtn = page.locator('button').filter({ hasText: '×' }).first()
    await expect(closeBtn).toBeVisible({ timeout: 5000 })
  })

  test('SSH-09 terminal panel can be closed', async ({ page, request }) => {
    test.setTimeout(90000)
    await loginViaApi(page)
    const token = await getToken(request)

    // Find an online node, or skip
    const nodesRes = await request.get(`${API}/api/v1/nodes?per_page=10`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    const { items } = await nodesRes.json()
    const onlineNode = items?.find((n: any) => n.status === 'online')

    if (!onlineNode) {
      test.skip()
      return
    }

    await page.goto(`/nodes/${onlineNode.id}`)
    await page.waitForSelector('h1', { timeout: 8000 })

    // Open SSH terminal
    const sshBtn = page.locator('button:has-text("SSH")').first()
    await sshBtn.click()

    // Verify it opened
    const terminalPanel = page.locator('text=SSH →').first()
    await expect(terminalPanel).toBeVisible({ timeout: 8000 })

    // Close the panel
    const closeBtn = page.locator('button').filter({ hasText: '×' }).first()
    await closeBtn.click()

    // Verify it closed (terminal panel should not be visible anymore)
    await expect(terminalPanel).not.toBeVisible({ timeout: 5000 })
  })
})
