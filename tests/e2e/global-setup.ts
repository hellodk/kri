/**
 * Playwright global setup — seeds the prerequisites the E2E suite assumes exist.
 *
 * A pristine docker-compose stack boots with seeded users (SEED_LOCAL_* in CI) but
 * an otherwise empty fleet: no salt-master, no groups, no nodes. That state makes
 * the bootstrap flow impossible to exercise (#905):
 *   - FleetDashboard disables "+ Bootstrap Node" unless ≥1 salt-master is enabled (#538).
 *   - POST /ansible/bootstrap returns 400 unless the node belongs to a group.
 *   - Fleet table/filter specs need ≥1 node row to assert against.
 *
 * This setup runs ONCE before the suite and is fully idempotent (safe on re-run /
 * retry): it only creates an entity when an equivalent one is absent. Specs refer
 * to the seeded entities by the names exported from helpers.ts (SEED).
 */
import { request as pwRequest, type APIRequestContext } from '@playwright/test'
import { ADMIN, API, SEED } from './helpers'

async function login(ctx: APIRequestContext): Promise<string> {
  // The API rate-limits logins (10/min); retry on 429 with a short backoff.
  for (let i = 0; i < 6; i++) {
    const res = await ctx.post(`${API}/auth/login`, { data: ADMIN })
    if (res.status() === 429) {
      await new Promise((r) => setTimeout(r, 10_000))
      continue
    }
    if (!res.ok()) {
      throw new Error(`global-setup: admin login failed (${res.status()}): ${await res.text()}`)
    }
    return (await res.json()).access_token
  }
  throw new Error('global-setup: admin login still rate-limited after retries')
}

export default async function globalSetup() {
  const ctx = await pwRequest.newContext({ baseURL: API })
  try {
    const token = await login(ctx)
    const auth = { Authorization: `Bearer ${token}` }

    // 1) Enabled salt-master — unblocks the bootstrap button + empty-state CTA.
    const mastersRes = await ctx.get(`${API}/api/v1/salt/masters`, { headers: auth })
    const masters: Array<{ name: string; enabled: boolean }> = await mastersRes.json()
    if (!masters.some((m) => m.enabled)) {
      const created = await ctx.post(`${API}/api/v1/salt/masters`, {
        headers: auth,
        data: { name: SEED.masterName, address: '127.0.0.1', enabled: true, is_default: true },
      })
      if (![200, 201].includes(created.status())) {
        throw new Error(`global-setup: create salt-master failed (${created.status()}): ${await created.text()}`)
      }
    }

    // 2) Static group with SSH credentials — makes added nodes bootstrap-eligible.
    const groupsRes = await ctx.get(`${API}/api/v1/groups?per_page=100`, { headers: auth })
    const groups: Array<{ id: string; name: string }> = (await groupsRes.json()).items ?? []
    let groupId = groups.find((g) => g.name === SEED.groupName)?.id
    if (!groupId) {
      const created = await ctx.post(`${API}/api/v1/groups`, {
        headers: auth,
        data: { name: SEED.groupName, type: 'static' },
      })
      if (![200, 201].includes(created.status())) {
        throw new Error(`global-setup: create group failed (${created.status()}): ${await created.text()}`)
      }
      groupId = (await created.json()).id
    }
    // Always (re)assert SSH creds on the group — patch is idempotent.
    const credRes = await ctx.patch(`${API}/api/v1/groups/${groupId}/credentials`, {
      headers: auth,
      data: { ...SEED.groupSsh, ssh_auth_mode: 'password', session_max_mins: 30 },
    })
    if (credRes.status() !== 200) {
      throw new Error(`global-setup: set group creds failed (${credRes.status()}): ${await credRes.text()}`)
    }

    // 3) Seed nodes (status "unknown") so the fleet table + filters have data.
    //    Add them to the seeded group so they are bootstrap-eligible.
    for (const minionId of SEED.nodeMinionIds) {
      const create = await ctx.post(`${API}/api/v1/nodes`, {
        headers: auth,
        data: { minion_id: minionId },
      })
      // 409 → node already exists from a prior run; fetch its id below.
      let nodeId: string | undefined
      if ([200, 201].includes(create.status())) {
        nodeId = (await create.json()).id
      } else if (create.status() === 409) {
        const look = await ctx.get(`${API}/api/v1/nodes?search=${encodeURIComponent(minionId)}&per_page=5`, {
          headers: auth,
        })
        const items: Array<{ id: string; minion_id: string }> = (await look.json()).items ?? []
        nodeId = items.find((n) => n.minion_id === minionId)?.id
      } else {
        throw new Error(`global-setup: create node ${minionId} failed (${create.status()}): ${await create.text()}`)
      }
      if (nodeId) {
        // Idempotent membership add — tolerate 409 (already a member).
        await ctx.post(`${API}/api/v1/groups/${groupId}/members`, {
          headers: auth,
          data: { node_id: nodeId },
        })
      }
    }
  } finally {
    await ctx.dispose()
  }
}
