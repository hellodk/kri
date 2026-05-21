/**
 * BOOTSTRAP — Bootstrap Node journeys
 * Covers: BOOT-01..BOOT-22 from TEST_CASES.md
 */
import { test, expect } from '@playwright/test'
import { loginViaApi, ADMIN, API } from './helpers'

test.describe('Bootstrap Node', () => {

  test.beforeEach(async ({ page }) => {
    await loginViaApi(page)
  })

  // ── Modal open / structure ──────────────────────────────────────────────────

  test('BOOT-01 modal opens from fleet dashboard', async ({ page }) => {
    await page.click('button:has-text("+ Bootstrap Node")')
    await expect(page.locator('h2:has-text("Bootstrap Mac Mini")')).toBeVisible()
    await expect(page.locator('button:has-text("Single node")')).toBeVisible()
    await expect(page.locator('button:has-text("Bulk")')).toBeVisible()
    await page.click('button:has-text("×")')
  })

  test('BOOT-02 playbook preview toggle shows YAML', async ({ page }) => {
    await page.click('button:has-text("+ Bootstrap Node")')
    await page.click('text=Preview bootstrap playbook')
    await expect(page.locator('pre:has-text("hosts")')).toBeVisible()
    await page.locator('button:has-text("×")').click()
  })

  test('BOOT-03 existing minion ID auto-fills IP', async ({ page }) => {
    await page.click('button:has-text("+ Bootstrap Node")')
    // Type a known minion ID (mac-mini-01 exists in seed data)
    await page.fill('input[placeholder="mac-mini-01"]', 'mac-mini-01')
    await expect(page.locator('text=Node found in fleet')).toBeVisible({ timeout: 5000 })
    await page.locator('button:has-text("×")').click()
  })

  test('BOOT-04 IP field locked for existing node', async ({ page }) => {
    await page.click('button:has-text("+ Bootstrap Node")')
    await page.fill('input[placeholder="mac-mini-01"]', 'mac-mini-01')
    await expect(page.locator('text=Node found in fleet')).toBeVisible({ timeout: 5000 })
    const ipInput = page.locator('input[placeholder="10.0.1.11"]')
    await expect(ipInput).toHaveAttribute('readonly')
    await page.locator('button:has-text("×")').click()
  })

  test('BOOT-05 new minion ID shows editable IP field', async ({ page }) => {
    await page.click('button:has-text("+ Bootstrap Node")')
    await page.fill('input[placeholder="mac-mini-01"]', 'brand-new-node-xyz')
    // Wait for search to fire (min 3 chars, debounce)
    await page.waitForTimeout(1500)
    await expect(page.locator('text=New node')).toBeVisible({ timeout: 5000 })
    const ipInput = page.locator('input[placeholder="10.0.1.11"]')
    await expect(ipInput).not.toHaveAttribute('readonly')
    await page.locator('button:has-text("×")').click()
  })

  test('BOOT-B01 switch to bulk mode shows textarea', async ({ page }) => {
    await page.click('button:has-text("+ Bootstrap Node")')
    await page.click('button:has-text("Bulk")')
    await expect(page.locator('textarea')).toBeVisible()
    await page.locator('button:has-text("×")').click()
  })

  test('BOOT-B02 bulk textarea parses host count', async ({ page }) => {
    await page.click('button:has-text("+ Bootstrap Node")')
    await page.click('button:has-text("Bulk")')
    await page.fill('textarea', 'mac-01  10.0.1.101\nmac-02  10.0.1.102')
    await expect(page.locator('text=2 hosts detected')).toBeVisible()
    await page.locator('button:has-text("×")').click()
  })

  test('BOOT-B03 comment lines are ignored', async ({ page }) => {
    await page.click('button:has-text("+ Bootstrap Node")')
    await page.click('button:has-text("Bulk")')
    await page.fill('textarea', '# this is a comment\nmac-01  10.0.1.101')
    await expect(page.locator('text=1 host detected')).toBeVisible()
    await page.locator('button:has-text("×")').click()
  })

  test('BOOT-B04 extra tags parsed from bulk line', async ({ page }) => {
    await page.click('button:has-text("+ Bootstrap Node")')
    await page.click('button:has-text("Bulk")')
    await page.fill('textarea', 'mac-01  10.0.1.101  serial=ABC123  location=rack-A')
    await expect(page.locator('text=extra tags will be applied')).toBeVisible()
    await page.locator('button:has-text("×")').click()
  })

  // ── API tests ───────────────────────────────────────────────────────────────

  test('BOOT-15 bootstrap API returns 202 with pending status', async ({ request }) => {
    const loginRes = await request.post(`${API}/auth/login`, {
      data: { email: ADMIN.email, password: ADMIN.password },
    })
    const { access_token } = await loginRes.json()
    const res = await request.post(`${API}/api/v1/ansible/bootstrap`, {
      headers: { Authorization: `Bearer ${access_token}` },
      data: { minion_id: `e2e-test-node-${Date.now()}`, target_ip: '192.168.99.99' },
    })
    // 200 or 202 both acceptable
    expect([200, 202]).toContain(res.status())
    const body = await res.json()
    expect(body).toHaveProperty('node_id')
    expect(body).toHaveProperty('bootstrap_status')
    expect(['pending', 'bootstrapping']).toContain(body.bootstrap_status)
    // Clean up: cancel the job
    await request.post(`${API}/api/v1/ansible/bootstrap/${body.node_id}/cancel`, {
      headers: { Authorization: `Bearer ${access_token}` },
    })
  })

  test('BOOT-16 second bootstrap on same node returns 409', async ({ request }) => {
    const loginRes = await request.post(`${API}/auth/login`, {
      data: { email: ADMIN.email, password: ADMIN.password },
    })
    const { access_token } = await loginRes.json()
    const minionId = `e2e-duplicate-${Date.now()}`
    const first = await request.post(`${API}/api/v1/ansible/bootstrap`, {
      headers: { Authorization: `Bearer ${access_token}` },
      data: { minion_id: minionId, target_ip: '192.168.99.98' },
    })
    const { node_id } = await first.json()
    const second = await request.post(`${API}/api/v1/ansible/bootstrap`, {
      headers: { Authorization: `Bearer ${access_token}` },
      data: { minion_id: minionId, target_ip: '192.168.99.98' },
    })
    expect(second.status()).toBe(409)
    await request.post(`${API}/api/v1/ansible/bootstrap/${node_id}/cancel`, {
      headers: { Authorization: `Bearer ${access_token}` },
    })
  })

  test('BOOT-18 path traversal in minion ID is rejected', async ({ request }) => {
    const loginRes = await request.post(`${API}/auth/login`, {
      data: { email: ADMIN.email, password: ADMIN.password },
    })
    const { access_token } = await loginRes.json()
    const res = await request.post(`${API}/api/v1/ansible/bootstrap`, {
      headers: { Authorization: `Bearer ${access_token}` },
      data: { minion_id: '../etc/passwd', target_ip: '10.0.0.1' },
    })
    // Should fail with 400 or 422
    expect([400, 422]).toContain(res.status())
  })

  test('BOOT-19 cancel endpoint resets bootstrap status', async ({ request }) => {
    const loginRes = await request.post(`${API}/auth/login`, {
      data: { email: ADMIN.email, password: ADMIN.password },
    })
    const { access_token } = await loginRes.json()
    const start = await request.post(`${API}/api/v1/ansible/bootstrap`, {
      headers: { Authorization: `Bearer ${access_token}` },
      data: { minion_id: `e2e-cancel-${Date.now()}`, target_ip: '192.168.99.97' },
    })
    const { node_id } = await start.json()
    const cancel = await request.post(`${API}/api/v1/ansible/bootstrap/${node_id}/cancel`, {
      headers: { Authorization: `Bearer ${access_token}` },
    })
    expect(cancel.status()).toBe(200)
    const body = await cancel.json()
    expect(body.bootstrap_status).toBe('failed')
  })

  test('BOOT-21 log endpoint returns pillar and stdout fields', async ({ request }) => {
    const loginRes = await request.post(`${API}/auth/login`, {
      data: { email: ADMIN.email, password: ADMIN.password },
    })
    const { access_token } = await loginRes.json()
    const start = await request.post(`${API}/api/v1/ansible/bootstrap`, {
      headers: { Authorization: `Bearer ${access_token}` },
      data: { minion_id: `e2e-logs-${Date.now()}`, target_ip: '192.168.99.96' },
    })
    const { node_id } = await start.json()
    const logs = await request.get(`${API}/api/v1/ansible/bootstrap/${node_id}/logs`, {
      headers: { Authorization: `Bearer ${access_token}` },
    })
    expect(logs.status()).toBe(200)
    const body = await logs.json()
    expect(body).toHaveProperty('pillar')
    expect(body).toHaveProperty('ansible_stdout')
    expect(body).toHaveProperty('bootstrap_status')
    await request.post(`${API}/api/v1/ansible/bootstrap/${node_id}/cancel`, {
      headers: { Authorization: `Bearer ${access_token}` },
    })
  })
})
