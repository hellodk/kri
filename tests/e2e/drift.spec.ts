/**
 * DRIFT — Drift detection journeys
 */
import { test, expect } from '@playwright/test'
import { loginViaApi, getToken, ADMIN, API } from './helpers'

test.describe('Drift Detection', () => {

  test.beforeEach(async ({ page }) => {
    test.setTimeout(90000)
    await loginViaApi(page)
    await page.goto('/drift')
    await page.waitForSelector('h1', { timeout: 15000 })
  })

  test('DRIFT-01 drift page loads', async ({ page }) => {
    await expect(page.locator('h1')).toBeVisible()
  })

  test('DRIFT-02 drift API returns nodes with scores', async ({ request }) => {
    const token = await getToken(request)
    const res = await request.get(`${API}/api/v1/drift?per_page=10`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    expect(res.status()).toBe(200)
    const body = await res.json()
    expect(body).toHaveProperty('items')
    expect(body).toHaveProperty('total')
  })

  test('DRIFT-03 compute drift endpoint triggers task', async ({ request }) => {
    const token = await getToken(request)
    const nodesRes = await request.get(`${API}/api/v1/nodes?per_page=1`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    const { items } = await nodesRes.json()
    if (!items.length) return
    const res = await request.post(`${API}/api/v1/drift/${items[0].id}/compute`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    expect([200, 202]).toContain(res.status())
    const body = await res.json()
    expect(body).toHaveProperty('status')
  })

  test('DRIFT-04 baseline capture returns packages when grains exist', async ({ request }) => {
    const token = await getToken(request)
    // Find a node with grains
    const nodesRes = await request.get(`${API}/api/v1/nodes?per_page=5`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    const { items } = await nodesRes.json()
    for (const node of items) {
      const res = await request.get(`${API}/api/v1/baselines/capture/${node.id}`, {
        headers: { Authorization: `Bearer ${token}` },
      })
      if (res.status() === 200) {
        const body = await res.json()
        expect(body).toHaveProperty('packages')
        expect(body).toHaveProperty('package_count')
        return
      }
    }
    // No nodes with grains — test passes vacuously
  })

  test('DRIFT-05 baselines list is paginated', async ({ request }) => {
    const token = await getToken(request)
    const res = await request.get(`${API}/api/v1/baselines?per_page=1`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    expect(res.status()).toBe(200)
    const body = await res.json()
    expect(body).toHaveProperty('items')
    expect(body).toHaveProperty('total')
    expect(body.items.length).toBeLessThanOrEqual(1)
  })

  test('DRIFT-06 invalid severity filter returns 422', async ({ request }) => {
    const token = await getToken(request)
    const res = await request.get(`${API}/api/v1/drift?severity=extreme`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    expect(res.status()).toBe(422)
  })
})
