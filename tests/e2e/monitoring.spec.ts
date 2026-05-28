import { test, expect } from '@playwright/test'

test.describe('Monitoring Page', () => {
  test.beforeEach(async ({ page }) => {
    // Log in as admin
    await page.goto('/login')
    await page.fill('input[name="username"]', 'admin@fleet.local')
    await page.fill('input[name="password"]', 'changeme')
    await page.click('button[type="submit"]')
    await page.waitForURL('/fleet')
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
    // At least one of the four cards should be visible
    await expect(
      page.locator('text=Node Status, text=Celery Queues, text=Alert Events, text=HTTP Requests').first()
    ).toBeVisible({ timeout: 15000 })
  })
})
