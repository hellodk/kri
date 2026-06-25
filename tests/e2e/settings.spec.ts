/**
 * SETTINGS — Platform settings journeys
 */
import { test, expect } from '@playwright/test'
import { loginViaApi, getToken, ADMIN, VIEWER, API } from './helpers'

test.describe('Settings', () => {

  test.beforeEach(async ({ page }) => {
    test.setTimeout(90000)
    await loginViaApi(page)
    await page.goto('/settings')
    await page.waitForSelector('h1', { timeout: 8000 })
  })

  test('SETTINGS-01 settings page loads with tabs', async ({ page }) => {
    await expect(page.locator('h1')).toBeVisible()
    // Tab layout: General, Bootstrap, Remote Access, Integrations, Advanced
    const tabs = ['General', 'Bootstrap', 'Remote Access', 'Integrations', 'Advanced']
    for (const tab of tabs) {
      await expect(
        page.locator(`button:has-text("${tab}")`).first()
      ).toBeVisible({ timeout: 3000 })
    }
  })

  test('SETTINGS-02 General tab shows kri API URL field', async ({ page }) => {
    // General tab is active by default
    await expect(
      page.locator('input[placeholder*="100.89"]').or(
        page.locator('input[placeholder*="YOUR_SERVER"]').or(
          page.locator('input[placeholder*="http://"]')
        )
      ).first()
    ).toBeVisible({ timeout: 3000 })
  })

  test('SETTINGS-03 Integrations tab shows CxOne and SonarQube', async ({ page }) => {
    await page.click('button:has-text("Integrations")')
    await expect(
      page.locator('h2:has-text("Security Integrations")').or(
        page.locator('label:has-text("CxOne URL")')
      ).first()
    ).toBeVisible({ timeout: 3000 })
    await expect(page.locator('label:has-text("SonarQube URL")')).toBeVisible({ timeout: 3000 })
  })

  test('SETTINGS-04 Remote Access tab shows VNC toggle', async ({ page }) => {
    await page.click('button:has-text("Remote Access")')
    await expect(page.locator('p:has-text("VNC Screen Share")')).toBeVisible({ timeout: 3000 })
  })

  test('SETTINGS-05 settings API requires admin', async ({ request }) => {
    const loginRes = await request.post(`${API}/auth/login`, {
      data: VIEWER,
    })
    const { access_token } = await loginRes.json()
    const res = await request.get(`${API}/api/v1/settings`, {
      headers: { Authorization: `Bearer ${access_token}` },
    })
    expect(res.status()).toBe(403)
  })

  test('SETTINGS-06 Bootstrap tab shows controller pubkey section', async ({ page }) => {
    await page.click('button:has-text("Bootstrap")')
    // Controller pubkey section or message about generating it
    await expect(
      page.locator('text=Controller SSH Public Key').or(
        page.locator('text=controller_pubkey').or(
          page.locator('text=Controller').or(page.locator('text=authorized_key'))
        )
      ).first()
    ).toBeVisible({ timeout: 3000 })
  })
})
