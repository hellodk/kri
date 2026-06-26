/**
 * PLAYBOOKS — Ansible playbook runner journeys
 * Covers: PLAY-01..PLAY-21 from TEST_CASES.md
 */
import { test, expect } from '@playwright/test'
import { loginViaApi, ADMIN, API } from './helpers'

test.describe('Playbooks', () => {

  test.beforeEach(async ({ page }) => {
    await loginViaApi(page)
    await page.goto('/playbooks')
    await page.waitForSelector('h1', { timeout: 8000 })
  })

  test('PLAY-01 playbooks page loads', async ({ page }) => {
    await expect(page.locator('h1')).toBeVisible()
  })

  test('PLAY-02 bootstrap playbook card shown', async ({ page }) => {
    // The card shows the play's `- name:` from bootstrap_node.yml, not the file name.
    await expect(page.locator('text=Bootstrap fleet node').first()).toBeVisible({ timeout: 8000 })
  })

  test('PLAY-05 run button opens confirmation dialog', async ({ page }) => {
    const runBtn = page.locator('button').filter({ hasText: /▷ Run|Run/ }).first()
    await expect(runBtn).toBeVisible({ timeout: 5000 })
    await runBtn.click({ force: true })
    await expect(page.locator('text=Run playbook?').or(page.locator('text=will run against')).first()).toBeVisible({ timeout: 3000 })
  })

  test('PLAY-06 cancel confirmation closes dialog without running', async ({ page }) => {
    const runBtn = page.locator('button').filter({ hasText: /▷ Run|Run/ }).first()
    await runBtn.click({ force: true })
    await page.click('button:has-text("Cancel")')
    await expect(page.locator('text=Run playbook?')).not.toBeVisible()
  })

  // ── API tests ───────────────────────────────────────────────────────────────

  test('PLAY-16 list playbooks API returns expected fields', async ({ request }) => {
    const loginRes = await request.post(`${API}/auth/login`, {
      data: { email: ADMIN.email, password: ADMIN.password },
    })
    const { access_token } = await loginRes.json()
    const res = await request.get(`${API}/api/v1/ansible/playbooks`, {
      headers: { Authorization: `Bearer ${access_token}` },
    })
    expect(res.status()).toBe(200)
    const body = await res.json()
    expect(Array.isArray(body)).toBeTruthy()
    // API contract must not be silently skipped on an empty array — the playbooks
    // directory must always contain at least the built-in bootstrap playbook (#807).
    expect(body.length).toBeGreaterThan(0)
    const entry = body[0]
    expect(entry).toHaveProperty('filename')
    expect(entry).toHaveProperty('name')
    expect(entry).toHaveProperty('entry_type')
  })

  test('PLAY-17 path traversal in playbook run is rejected', async ({ request }) => {
    const loginRes = await request.post(`${API}/auth/login`, {
      data: { email: ADMIN.email, password: ADMIN.password },
    })
    const { access_token } = await loginRes.json()
    const res = await request.post(`${API}/api/v1/ansible/playbooks/run`, {
      headers: { Authorization: `Bearer ${access_token}` },
      data: {
        playbook: '../../etc/passwd',
        target_type: 'node',
        target_id: '00000000-0000-0000-0000-000000000000',
      },
    })
    expect([400, 404, 422]).toContain(res.status())
  })

  test('PLAY-18 get playbook content returns YAML', async ({ request }) => {
    const loginRes = await request.post(`${API}/auth/login`, {
      data: { email: ADMIN.email, password: ADMIN.password },
    })
    const { access_token } = await loginRes.json()
    const res = await request.get(`${API}/api/v1/ansible/playbooks/content?filename=bootstrap_node.yml`, {
      headers: { Authorization: `Bearer ${access_token}` },
    })
    expect(res.status()).toBe(200)
    const body = await res.json()
    expect(body).toHaveProperty('filename', 'bootstrap_node.yml')
    expect(body).toHaveProperty('content')
    expect(body.content).toContain('hosts:')
  })

  test('PLAY-20 unknown job ID returns 404', async ({ request }) => {
    const loginRes = await request.post(`${API}/auth/login`, {
      data: { email: ADMIN.email, password: ADMIN.password },
    })
    const { access_token } = await loginRes.json()
    const res = await request.get(`${API}/api/v1/ansible/jobs/00000000-0000-0000-0000-000000000000`, {
      headers: { Authorization: `Bearer ${access_token}` },
    })
    expect(res.status()).toBe(404)
  })
})
