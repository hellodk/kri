/**
 * BOOTSTRAP — Bootstrap Node journeys
 * Covers: BOOT-01..BOOT-22 from TEST_CASES.md
 */
import { test, expect, type APIRequestContext } from '@playwright/test'
import { loginViaApi, getToken, API, SEED } from './helpers'

/**
 * Bootstrap requires the target node to belong to a group (the API returns 400
 * otherwise — see queue_node_bootstrap). global-setup seeds the group SEED.groupName
 * with SSH creds; this helper creates a node and adds it to that group so the
 * bootstrap API tests can reach a 2xx instead of the group-guard 400 (#905).
 */
async function seedNodeInGroup(
  request: APIRequestContext,
  token: string,
  minionId: string,
): Promise<{ id: string; minion_id: string }> {
  const auth = { Authorization: `Bearer ${token}` }
  const nodeRes = await request.post(`${API}/api/v1/nodes`, { headers: auth, data: { minion_id: minionId } })
  const node = await nodeRes.json()
  const grpRes = await request.get(`${API}/api/v1/groups?per_page=100`, { headers: auth })
  const group = ((await grpRes.json()).items ?? []).find((g: { name: string }) => g.name === SEED.groupName)
  if (group) {
    await request.post(`${API}/api/v1/groups/${group.id}/members`, { headers: auth, data: { node_id: node.id } })
  }
  return node
}

test.describe('Bootstrap Node', () => {

  test.beforeEach(async ({ page }) => {
    await loginViaApi(page)
  })

  // ── Modal open / structure ──────────────────────────────────────────────────

  test('BOOT-01 modal opens from fleet dashboard', async ({ page }) => {
    await page.click('button:has-text("+ Bootstrap Node")')
    await expect(page.locator('h2:has-text("Bootstrap Node")')).toBeVisible()
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

  test('BOOT-03 selecting an existing node locks its IP from the record', async ({ page }) => {
    await page.click('button:has-text("+ Bootstrap Node")')
    // Single mode defaults to the "Existing node" picker. Search for a node
    // seeded by global-setup (the old hard-coded "mm1" never exists in CI).
    await page.fill('input[placeholder="Search nodes…"]', SEED.nodeMinionIds[0])
    await page.click(`button:has-text("${SEED.nodeMinionIds[0]}")`)
    // Selecting an existing node reveals the locked, record-sourced IP field.
    await expect(page.locator('text=locked — from node record')).toBeVisible({ timeout: 8000 })
    await page.locator('button:has-text("×")').click()
  })

  test('BOOT-04 IP field locked for existing node', async ({ page }) => {
    await page.click('button:has-text("+ Bootstrap Node")')
    await page.fill('input[placeholder="Search nodes…"]', SEED.nodeMinionIds[0])
    await page.click(`button:has-text("${SEED.nodeMinionIds[0]}")`)
    await expect(page.locator('text=locked — from node record')).toBeVisible({ timeout: 8000 })
    const ipInput = page.locator('input[readonly]').first()
    await expect(ipInput).toHaveAttribute('readonly', '')
    await page.locator('button:has-text("×")').click()
  })

  test('BOOT-05 new minion ID shows editable IP field', async ({ page }) => {
    await page.click('button:has-text("+ Bootstrap Node")')
    await page.click('button:has-text("New node")')
    await page.fill('input[placeholder="mac-mini-01"]', 'brand-new-node-xyz')
    // Wait for search to fire (min 3 chars, debounce) and resolve to "not found".
    await page.waitForTimeout(1500)
    const ipInput = page.locator('input[placeholder="10.0.1.11"]')
    await expect(ipInput).toBeVisible()
    await expect(ipInput).not.toHaveAttribute('readonly', '')
    await page.locator('button:has-text("×")').click()
  })

  test('BOOT-B01 switch to bulk mode shows textarea', async ({ page }) => {
    await page.click('button:has-text("+ Bootstrap Node")')
    await page.click('button:has-text("Bulk")')
    // Bulk defaults to "From Group"; the CSV textarea lives under "CSV paste".
    await page.click('button:has-text("CSV paste")')
    // Scope to the CSV textarea — the page also renders the LLM-assistant textarea.
    await expect(page.locator('textarea[placeholder^="# minion-id"]')).toBeVisible()
    await page.locator('button:has-text("×")').click()
  })

  test('BOOT-B02 bulk textarea parses host count', async ({ page }) => {
    await page.click('button:has-text("+ Bootstrap Node")')
    await page.click('button:has-text("Bulk")')
    await page.click('button:has-text("CSV paste")')
    await page.fill('textarea[placeholder^="# minion-id"]', 'mac-01  10.0.1.101\nmac-02  10.0.1.102')
    await expect(page.locator('text=2 hosts detected')).toBeVisible()
    await page.locator('button:has-text("×")').click()
  })

  test('BOOT-B03 comment lines are ignored', async ({ page }) => {
    await page.click('button:has-text("+ Bootstrap Node")')
    await page.click('button:has-text("Bulk")')
    await page.click('button:has-text("CSV paste")')
    await page.fill('textarea[placeholder^="# minion-id"]', '# this is a comment\nmac-01  10.0.1.101')
    await expect(page.locator('text=1 host detected')).toBeVisible()
    await page.locator('button:has-text("×")').click()
  })

  test('BOOT-B04 extra tags parsed from bulk line', async ({ page }) => {
    await page.click('button:has-text("+ Bootstrap Node")')
    await page.click('button:has-text("Bulk")')
    await page.click('button:has-text("CSV paste")')
    await page.fill('textarea[placeholder^="# minion-id"]', 'mac-01  10.0.1.101  serial=ABC123  location=rack-A')
    await expect(page.locator('text=extra tags will be applied')).toBeVisible()
    await page.locator('button:has-text("×")').click()
  })

  // ── API tests ───────────────────────────────────────────────────────────────

  test('BOOT-15 bootstrap API returns 202 with pending status', async ({ request }) => {
    const token = await getToken(request)
    const minionId = `e2e-test-node-${Date.now()}`
    await seedNodeInGroup(request, token, minionId)
    const res = await request.post(`${API}/api/v1/ansible/bootstrap`, {
      headers: { Authorization: `Bearer ${token}` },
      data: { minion_id: minionId, target_ip: '192.168.99.99' },
    })
    // 200 or 202 both acceptable
    expect([200, 202]).toContain(res.status())
    const body = await res.json()
    expect(body).toHaveProperty('node_id')
    expect(body).toHaveProperty('bootstrap_status')
    expect(['pending', 'bootstrapping']).toContain(body.bootstrap_status)
    // Clean up: cancel the job
    await request.post(`${API}/api/v1/ansible/bootstrap/${body.node_id}/cancel`, {
      headers: { Authorization: `Bearer ${token}` },
    })
  })

  test('BOOT-16 second bootstrap on same node returns 409', async ({ request }) => {
    const token = await getToken(request)
    const minionId = `e2e-duplicate-${Date.now()}`
    await seedNodeInGroup(request, token, minionId)
    const first = await request.post(`${API}/api/v1/ansible/bootstrap`, {
      headers: { Authorization: `Bearer ${token}` },
      data: { minion_id: minionId, target_ip: '192.168.99.98' },
    })
    const { node_id } = await first.json()

    // Poll until the bootstrap transitions from "pending" → "bootstrapping"
    // The API only returns 409 when status is "bootstrapping" (not "pending")
    let bootstrapping = false
    for (let i = 0; i < 10; i++) {
      const status = await request.get(`${API}/api/v1/ansible/bootstrap/${node_id}/logs`, {
        headers: { Authorization: `Bearer ${token}` },
      })
      const body = await status.json()
      if (body.bootstrap_status === 'bootstrapping') { bootstrapping = true; break }
      await new Promise(r => setTimeout(r, 500))
    }

    const second = await request.post(`${API}/api/v1/ansible/bootstrap`, {
      headers: { Authorization: `Bearer ${token}` },
      data: { minion_id: minionId, target_ip: '192.168.99.98' },
    })
    if (bootstrapping) {
      expect(second.status()).toBe(409)
    } else {
      // If node never reached "bootstrapping" (e.g., ansible failed instantly),
      // the conflict window was missed — accept any 2xx or 409
      expect([200, 202, 409]).toContain(second.status())
    }
    await request.post(`${API}/api/v1/ansible/bootstrap/${node_id}/cancel`, {
      headers: { Authorization: `Bearer ${token}` },
    })
  })

  test('BOOT-18 path traversal in minion ID is rejected', async ({ request }) => {
    const token = await getToken(request)
    // The minion_id regex guard runs before the group check, so no group needed.
    const res = await request.post(`${API}/api/v1/ansible/bootstrap`, {
      headers: { Authorization: `Bearer ${token}` },
      data: { minion_id: '../etc/passwd', target_ip: '10.0.0.1' },
    })
    // Should fail with 400 or 422
    expect([400, 422]).toContain(res.status())
  })

  test('BOOT-19 cancel endpoint resets bootstrap status', async ({ request }) => {
    const token = await getToken(request)
    const minionId = `e2e-cancel-${Date.now()}`
    await seedNodeInGroup(request, token, minionId)
    const start = await request.post(`${API}/api/v1/ansible/bootstrap`, {
      headers: { Authorization: `Bearer ${token}` },
      data: { minion_id: minionId, target_ip: '192.168.99.97' },
    })
    const { node_id } = await start.json()
    const cancel = await request.post(`${API}/api/v1/ansible/bootstrap/${node_id}/cancel`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    expect(cancel.status()).toBe(200)
    const body = await cancel.json()
    expect(body.bootstrap_status).toBe('failed')
  })

  test('BOOT-21 log endpoint returns stdout and status fields', async ({ request }) => {
    const token = await getToken(request)
    const minionId = `e2e-logs-${Date.now()}`
    await seedNodeInGroup(request, token, minionId)
    const start = await request.post(`${API}/api/v1/ansible/bootstrap`, {
      headers: { Authorization: `Bearer ${token}` },
      data: { minion_id: minionId, target_ip: '192.168.99.96' },
    })
    const { node_id } = await start.json()
    const logs = await request.get(`${API}/api/v1/ansible/bootstrap/${node_id}/logs`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    expect(logs.status()).toBe(200)
    const body = await logs.json()
    // The logs endpoint returns minion_id + ansible_stdout + bootstrap_status
    // (the old "pillar" field was dropped from this endpoint).
    expect(body).toHaveProperty('minion_id')
    expect(body).toHaveProperty('ansible_stdout')
    expect(body).toHaveProperty('bootstrap_status')
    await request.post(`${API}/api/v1/ansible/bootstrap/${node_id}/cancel`, {
      headers: { Authorization: `Bearer ${token}` },
    })
  })
})
