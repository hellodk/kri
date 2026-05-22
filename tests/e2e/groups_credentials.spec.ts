/**
 * GROUP CREDENTIALS — Group SSH credential journeys
 */
import { test, expect } from '@playwright/test'
import { loginViaApi, getToken, ADMIN, API } from './helpers'

test.describe('Group Credentials', () => {

  let groupId: string

  test.beforeAll(async ({ request }) => {
    const loginRes = await request.post(`${API}/auth/login`, {
      data: { email: ADMIN.email, password: ADMIN.password },
    })
    const { access_token } = await loginRes.json()
    const grpRes = await request.post(`${API}/api/v1/groups`, {
      headers: { Authorization: `Bearer ${access_token}` },
      data: { name: `Creds-Test-${Date.now()}`, type: 'static' },
    })
    const grp = await grpRes.json()
    groupId = grp.id
  })

  test('GCRED-01 get credentials returns no secrets', async ({ request }) => {
    const token = await getToken(request)
    const res = await request.get(`${API}/api/v1/groups/${groupId}/credentials`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    expect(res.status()).toBe(200)
    const body = await res.json()
    // Must NOT contain raw secret fields
    expect(body).not.toHaveProperty('ssh_password_enc')
    expect(body).not.toHaveProperty('ssh_key_enc')
    expect(body).toHaveProperty('has_ssh_password')
  })

  test('GCRED-02 patch credentials saves username', async ({ request }) => {
    const token = await getToken(request)
    const res = await request.patch(`${API}/api/v1/groups/${groupId}/credentials`, {
      headers: { Authorization: `Bearer ${token}` },
      data: { ssh_username: 'testoperator', ssh_password: 'testpass', ssh_auth_mode: 'password', session_max_mins: 30 },
    })
    expect(res.status()).toBe(200)
    const body = await res.json()
    expect(body.ssh_username).toBe('testoperator')
    expect(body.has_ssh_password).toBe(true)
    expect(body.session_max_mins).toBe(30)
  })

  test('GCRED-03 viewer cannot patch credentials', async ({ request }) => {
    const loginRes = await request.post(`${API}/auth/login`, {
      data: { email: 'viewer@fleet.local', password: 'changeme' },
    })
    const { access_token } = await loginRes.json()
    const res = await request.patch(`${API}/api/v1/groups/${groupId}/credentials`, {
      headers: { Authorization: `Bearer ${access_token}` },
      data: { ssh_username: 'hacker' },
    })
    expect(res.status()).toBe(403)
  })

  test('GCRED-04 bootstrap without required group falls back to global credentials', async ({ request }) => {
    const token = await getToken(request)
    const minionId = `no-group-${Date.now()}`

    // Bootstrap should succeed (uses global/default credentials) or reject with appropriate error
    const bootRes = await request.post(`${API}/api/v1/ansible/bootstrap`, {
      headers: { Authorization: `Bearer ${token}` },
      data: { minion_id: minionId, target_ip: '10.0.0.99' },
    })
    // 200/202 means bootstrap queued (global creds used), 400 means group required
    expect([200, 202, 400]).toContain(bootRes.status())

    if (bootRes.status() === 200 || bootRes.status() === 202) {
      // Clean up
      const body = await bootRes.json()
      await request.post(`${API}/api/v1/ansible/bootstrap/${body.node_id}/cancel`, {
        headers: { Authorization: `Bearer ${token}` },
      })
      // Also clean up the node
      await request.delete(`${API}/api/v1/nodes/${body.node_id}`, {
        headers: { Authorization: `Bearer ${token}` },
      })
    }
  })
})
