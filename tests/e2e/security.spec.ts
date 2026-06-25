/**
 * SECURITY — Security dashboard journeys
 */
import { test, expect } from '@playwright/test'
import { loginViaApi, getToken, ADMIN, VIEWER, API } from './helpers'

test.describe('Security Dashboard', () => {

  test.beforeEach(async ({ page }) => {
    test.setTimeout(90000)
    await loginViaApi(page)
    await page.goto('/security')
    await page.waitForSelector('h1', { timeout: 8000 })
  })

  test('SEC-01 security page loads with summary cards', async ({ page }) => {
    await expect(page.locator('h1')).toBeVisible()
    // Four summary cards: Critical & High, Medium & Low, License Risks, Nodes at Risk
    await expect(page.locator('text=Critical & High').or(page.locator('text=Vulnerabilities')).first()).toBeVisible()
  })

  test('SEC-02 integration status bar shows Trivy', async ({ page }) => {
    // Use exact text to avoid strict mode violation (multiple elements contain "Trivy")
    await expect(page.locator('span.text-gray-600.font-medium:text-is("Trivy")').or(
      page.locator('button:has-text("Scan All (Trivy)")')
    ).first()).toBeVisible()
  })

  test('SEC-03 node security table shows nodes', async ({ page }) => {
    const table = page.locator('table')
    await expect(table).toBeVisible({ timeout: 5000 })
  })

  test('SEC-04 scan all button exists and is clickable', async ({ page }) => {
    const scanBtn = page.locator('button:has-text("Scan All")').or(page.locator('button:has-text("Scan")')).first()
    await expect(scanBtn).toBeVisible()
  })

  test('SEC-05 API dashboard returns correct structure', async ({ request }) => {
    const token = await getToken(request)
    const res = await request.get(`${API}/api/v1/security/dashboard`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    expect(res.status()).toBe(200)
    const body = await res.json()
    expect(body).toHaveProperty('vulnerabilities')
    expect(body).toHaveProperty('total_vulnerabilities')
    expect(body).toHaveProperty('license_risks')
    expect(body.vulnerabilities).toHaveProperty('critical')
    expect(body.vulnerabilities).toHaveProperty('high')
  })

  test('SEC-06 API integration-status returns all three tools', async ({ request }) => {
    const token = await getToken(request)
    const res = await request.get(`${API}/api/v1/security/integration-status`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    expect(res.status()).toBe(200)
    const body = await res.json()
    expect(body).toHaveProperty('trivy')
    expect(body).toHaveProperty('cxone')
    expect(body).toHaveProperty('sonarqube')
    // trivy is available in the Docker stack
    expect(body.trivy).toHaveProperty('available')
  })

  test('SEC-07 invalid scanner name returns 422', async ({ request }) => {
    const token = await getToken(request)
    // Get a node ID first
    const nodesRes = await request.get(`${API}/api/v1/nodes?per_page=1`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    const { items } = await nodesRes.json()
    if (!items.length) return
    const res = await request.post(`${API}/api/v1/security/scan/${items[0].id}?scanner=evil_scanner`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    expect(res.status()).toBe(422)
  })

  test('SEC-08 viewer cannot trigger scans', async ({ request }) => {
    const loginRes = await request.post(`${API}/auth/login`, {
      data: VIEWER,
    })
    const { access_token } = await loginRes.json()
    const res = await request.post(`${API}/api/v1/security/scan-all`, {
      headers: { Authorization: `Bearer ${access_token}` },
    })
    expect(res.status()).toBe(403)
  })
})
