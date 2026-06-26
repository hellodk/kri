import { test, expect } from '@playwright/test'
import { loginViaApi } from './helpers'

test.describe('Monitoring Page', () => {
  test.beforeEach(async ({ page }) => {
    test.setTimeout(90000)
    // The login form has no name="username"/name="password" inputs (it uses
    // input[type="email"]/input[type="password"]), so the previous fill() calls
    // never matched and the page never logged in. Use the shared API-login helper
    // like every other authenticated spec (#905).
    await loginViaApi(page)
  })

  test('monitoring page renders without errors', async ({ page }) => {
    const errors: string[] = []
    page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()) })
    await page.goto('/monitoring')
    await page.waitForSelector('h1, h2, [data-testid="monitoring-page"]', { timeout: 10000 })
    expect(errors).toHaveLength(0)
  })

  test('monitoring page shows at least one metric card', async ({ page }) => {
    await page.goto('/monitoring')
    // At least one of the four SectionCard h2 titles should be visible
    // Titles: "Node Status", "Celery Queue Depth", "Alert Events (24h)", "HTTP Requests (since startup)"
    await expect(
      page.locator('h2').filter({ hasText: /Node Status|Celery Queue|Alert Events|HTTP Requests/i }).first()
    ).toBeVisible({ timeout: 15000 })
  })
})
