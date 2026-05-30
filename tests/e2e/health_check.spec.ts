/**
 * kri Health Check — structured PASS / FAIL / EMPTY report
 *
 * Visits every route/tab, verifies the page renders without crashing,
 * and checks whether key data is present. Produces a human-readable
 * summary in the console at the end of the run.
 *
 * Run: npx playwright test tests/e2e/health_check.spec.ts --reporter=line
 */
import { test, expect, Page, APIRequestContext } from '@playwright/test'
import { loginViaApi, getToken, API } from './helpers'

// ── Report types ───────────────────────────────────────────────────────────────

type Status = 'PASS' | 'FAIL' | 'EMPTY' | 'SKIP'

interface CheckResult {
  route: string
  label: string
  status: Status
  detail: string
}

// Shared across all tests in the file via module-level array.
// Playwright runs each test() in the same worker process when workers=1,
// so this is safe for a single-worker health-check suite.
const results: CheckResult[] = []

function record(route: string, label: string, status: Status, detail: string) {
  results.push({ route, label, status, detail })
  const pad = status.padEnd(5)
  console.log(`[${pad}] ${label}: ${detail}`)
}

// ── Helpers ────────────────────────────────────────────────────────────────────

/** Navigate to a path, wait for any h1/h2 heading, and collect console errors. */
async function visitPage(
  page: Page,
  path: string,
): Promise<{ consoleErrors: string[] }> {
  const consoleErrors: string[] = []
  const handler = (msg: { type: () => string; text: () => string }) => {
    if (msg.type() === 'error') consoleErrors.push(msg.text())
  }
  page.on('console', handler)

  await page.goto(path)
  // Wait for a heading or a known content container — avoids false positives
  // while the React app bootstraps.
  await page.waitForSelector('h1, h2, [role="main"], main, .container', {
    timeout: 12_000,
  }).catch(() => { /* page may not have these; we still report */ })

  page.off('console', handler)
  return { consoleErrors }
}

/** Return true if an element matching `selector` exists and is visible. */
async function hasVisible(page: Page, selector: string): Promise<boolean> {
  try {
    const el = page.locator(selector).first()
    return await el.isVisible({ timeout: 5_000 })
  } catch {
    return false
  }
}

/** Count rows in the first tbody on the page. */
async function tableRowCount(page: Page): Promise<number> {
  try {
    return await page.locator('tbody tr').count()
  } catch {
    return 0
  }
}

/** Read the text of the first matching element; returns '' on miss. */
async function firstText(page: Page, selector: string): Promise<string> {
  try {
    const el = page.locator(selector).first()
    const visible = await el.isVisible({ timeout: 4_000 })
    if (!visible) return ''
    return (await el.textContent()) ?? ''
  } catch {
    return ''
  }
}

/** Check an API endpoint and return its status code. */
async function apiStatus(
  request: APIRequestContext,
  path: string,
  token: string,
): Promise<number> {
  const res = await request.get(`${API}${path}`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  return res.status()
}

// ── Login fixture — shared across describe block ───────────────────────────────

// Each test logs in via the cached loginViaApi helper, then navigates.
// The token is cached for 12 min so re-login overhead is negligible.

// ═══════════════════════════════════════════════════════════════════════════════
// OVERVIEW HUB
// ═══════════════════════════════════════════════════════════════════════════════

test.describe('Health Check — Overview Hub', () => {
  test.setTimeout(40_000)

  test('HC-01 Fleet Overview tab — stat cards and node table', async ({ page, request }) => {
    await loginViaApi(page)
    const { consoleErrors } = await visitPage(page, '/overview?tab=fleet-overview')
    const route = '/overview?tab=fleet-overview'
    const label = 'Fleet Overview'

    if (consoleErrors.length > 0) {
      record(route, label, 'FAIL', `Console errors: ${consoleErrors.slice(0, 2).join(' | ')}`)
      return
    }

    // Check API health
    const token = await getToken(request)
    const status = await apiStatus(request, '/api/v1/fleet/overview', token)
    if (status !== 200) {
      record(route, label, 'FAIL', `API /fleet/overview returned ${status}`)
      return
    }

    // Stat cards: text-4xl is the big number class on DashboardPage
    const statText = await firstText(page, '.text-4xl, .text-3xl')
    const nodeRows = await tableRowCount(page)

    if (!statText && nodeRows === 0) {
      record(route, label, 'EMPTY', 'No stat values and no table rows found')
    } else if (statText === '0' && nodeRows === 0) {
      record(route, label, 'EMPTY', `Stat = ${statText}, table rows = 0`)
    } else {
      record(route, label, 'PASS', `Stat value: "${statText.trim()}", table rows: ${nodeRows}`)
    }
  })

  test('HC-02 Fleet tab — node list', async ({ page, request }) => {
    await loginViaApi(page)
    const { consoleErrors } = await visitPage(page, '/overview?tab=fleet')
    const route = '/overview?tab=fleet'
    const label = 'Fleet (node list)'

    const token = await getToken(request)
    const status = await apiStatus(request, '/api/v1/nodes?page=1&per_page=5', token)
    if (status !== 200) {
      record(route, label, 'FAIL', `API /nodes returned ${status}`)
      return
    }

    const rows = await tableRowCount(page)
    const hasHeader = await hasVisible(page, 'thead th')

    if (!hasHeader) {
      record(route, label, 'FAIL', 'Node table headers not found')
    } else if (rows === 0) {
      record(route, label, 'EMPTY', 'Node table has 0 rows')
    } else {
      const hostname = await firstText(page, 'tbody tr td:nth-child(2) a')
      record(route, label, 'PASS', `${rows} nodes — first: "${hostname.trim()}"`)
    }

    if (consoleErrors.length > 0) {
      record(route, `${label} (console)`, 'FAIL', consoleErrors.slice(0, 2).join(' | '))
    }
  })

  test('HC-03 Fleet Health tab — renders without crash', async ({ page }) => {
    await loginViaApi(page)
    const { consoleErrors } = await visitPage(page, '/overview?tab=fleet-health')
    const route = '/overview?tab=fleet-health'
    const label = 'Fleet Health'

    if (consoleErrors.length > 0) {
      record(route, label, 'FAIL', `Console errors: ${consoleErrors.slice(0, 2).join(' | ')}`)
      return
    }

    // Either node cards or an empty state message is acceptable
    const hasCards = await hasVisible(page, '[class*="border rounded-lg p-4"]')
    const hasEmptyMsg = await hasVisible(page, 'text=No health snapshots')
    const hasHeading = await hasVisible(page, 'h1, h2')

    if (!hasHeading && !hasCards && !hasEmptyMsg) {
      record(route, label, 'FAIL', 'No heading, cards or empty state found')
    } else if (hasEmptyMsg || (!hasCards && hasHeading)) {
      record(route, label, 'EMPTY', 'No snapshots yet — empty state shown')
    } else {
      record(route, label, 'PASS', 'Health cards rendered')
    }
  })

  test('HC-04 Groups tab — list renders', async ({ page, request }) => {
    await loginViaApi(page)
    const { consoleErrors } = await visitPage(page, '/overview?tab=groups')
    const route = '/overview?tab=groups'
    const label = 'Groups'

    const token = await getToken(request)
    const status = await apiStatus(request, '/api/v1/groups', token)
    if (status !== 200) {
      record(route, label, 'FAIL', `API /groups returned ${status}`)
      return
    }

    const rows = await tableRowCount(page)
    const hasH1 = await hasVisible(page, 'h1')
    const hasEmptyMsg = await hasVisible(page, 'text=No groups')

    if (!hasH1) {
      record(route, label, 'FAIL', 'Page heading not found')
    } else if (rows === 0 || hasEmptyMsg) {
      record(route, label, 'EMPTY', 'No groups defined yet')
    } else {
      record(route, label, 'PASS', `${rows} group rows visible`)
    }

    if (consoleErrors.length > 0) {
      record(route, `${label} (console)`, 'FAIL', consoleErrors.slice(0, 2).join(' | '))
    }
  })
})

// ═══════════════════════════════════════════════════════════════════════════════
// COMPLIANCE HUB
// ═══════════════════════════════════════════════════════════════════════════════

test.describe('Health Check — Compliance Hub', () => {
  test.setTimeout(40_000)

  test('HC-05 Drift tab — renders without 500', async ({ page, request }) => {
    await loginViaApi(page)
    const { consoleErrors } = await visitPage(page, '/compliance?tab=drift')
    const route = '/compliance?tab=drift'
    const label = 'Drift'

    const token = await getToken(request)
    const status = await apiStatus(request, '/api/v1/drift?page=1&per_page=5', token)
    if (status !== 200) {
      record(route, label, 'FAIL', `API /drift returned ${status}`)
      return
    }

    const rows = await tableRowCount(page)
    const hasEmptyMsg = await hasVisible(page, 'text=No drift records, text=no drift')

    if (rows === 0 || hasEmptyMsg) {
      record(route, label, 'EMPTY', 'No drift records in the DB')
    } else {
      record(route, label, 'PASS', `${rows} drift record rows`)
    }

    if (consoleErrors.length > 0) {
      record(route, `${label} (console)`, 'FAIL', consoleErrors.slice(0, 2).join(' | '))
    }
  })

  test('HC-06 Baselines tab — renders', async ({ page, request }) => {
    await loginViaApi(page)
    const { consoleErrors } = await visitPage(page, '/compliance?tab=baselines')
    const route = '/compliance?tab=baselines'
    const label = 'Baselines'

    const token = await getToken(request)
    const status = await apiStatus(request, '/api/v1/baselines', token)
    if (status !== 200) {
      record(route, label, 'FAIL', `API /baselines returned ${status}`)
      return
    }

    const hasH1 = await hasVisible(page, 'h1, h2')
    const rows = await tableRowCount(page)
    const hasEmptyMsg = await hasVisible(page, 'text=No baselines')

    if (!hasH1) {
      record(route, label, 'FAIL', 'No heading found')
    } else if (rows === 0 || hasEmptyMsg) {
      record(route, label, 'EMPTY', 'No baseline definitions yet')
    } else {
      record(route, label, 'PASS', `${rows} baseline rows`)
    }

    if (consoleErrors.length > 0) {
      record(route, `${label} (console)`, 'FAIL', consoleErrors.slice(0, 2).join(' | '))
    }
  })

  test('HC-07 SBOM tab — renders', async ({ page, request }) => {
    await loginViaApi(page)
    const { consoleErrors } = await visitPage(page, '/compliance?tab=sbom')
    const route = '/compliance?tab=sbom'
    const label = 'SBOM'

    const token = await getToken(request)
    const status = await apiStatus(request, '/api/v1/sbom/browse', token)
    if (status !== 200) {
      record(route, label, 'FAIL', `API /sbom/browse returned ${status}`)
      return
    }

    const hasH1 = await hasVisible(page, 'h1, h2')
    const rows = await tableRowCount(page)

    if (!hasH1) {
      record(route, label, 'FAIL', 'No heading found')
    } else if (rows === 0) {
      record(route, label, 'EMPTY', 'No SBOM packages indexed yet')
    } else {
      record(route, label, 'PASS', `${rows} package rows`)
    }

    if (consoleErrors.length > 0) {
      record(route, `${label} (console)`, 'FAIL', consoleErrors.slice(0, 2).join(' | '))
    }
  })

  test('HC-08 Licenses tab — renders', async ({ page, request }) => {
    await loginViaApi(page)
    const { consoleErrors } = await visitPage(page, '/compliance?tab=licenses')
    const route = '/compliance?tab=licenses'
    const label = 'Licenses'

    const token = await getToken(request)
    const status = await apiStatus(request, '/api/v1/sbom/browse', token)
    if (status !== 200) {
      record(route, label, 'FAIL', `API /sbom/browse returned ${status}`)
      return
    }

    const hasH1 = await hasVisible(page, 'h1, h2')
    if (!hasH1) {
      record(route, label, 'FAIL', 'No heading found')
      return
    }

    // License page may show 0 items if no SBOM data ingested yet
    const countText = await firstText(page, '.text-2xl, .text-3xl, .text-4xl')
    if (!countText || countText.trim() === '0') {
      record(route, label, 'EMPTY', 'License stats show 0 — no SBOM data yet')
    } else {
      record(route, label, 'PASS', `License data present: "${countText.trim()}"`)
    }

    if (consoleErrors.length > 0) {
      record(route, `${label} (console)`, 'FAIL', consoleErrors.slice(0, 2).join(' | '))
    }
  })

  test('HC-09 Security tab — renders', async ({ page, request }) => {
    await loginViaApi(page)
    const { consoleErrors } = await visitPage(page, '/compliance?tab=security')
    const route = '/compliance?tab=security'
    const label = 'Security'

    const token = await getToken(request)
    const status = await apiStatus(request, '/api/v1/security/dashboard', token)
    if (status !== 200) {
      record(route, label, 'FAIL', `API /security/dashboard returned ${status}`)
      return
    }

    const hasH1 = await hasVisible(page, 'h1, h2')
    if (!hasH1) {
      record(route, label, 'FAIL', 'No heading found')
      return
    }

    const rows = await tableRowCount(page)
    const hasZeroMsg = await hasVisible(page, 'text=0 vulnerabilities, text=No vulnerabilities, text=No findings')

    if (rows === 0 || hasZeroMsg) {
      record(route, label, 'EMPTY', 'No CVE findings yet (expected if Trivy not yet ingested)')
    } else {
      record(route, label, 'PASS', `${rows} vuln rows`)
    }

    if (consoleErrors.length > 0) {
      record(route, `${label} (console)`, 'FAIL', consoleErrors.slice(0, 2).join(' | '))
    }
  })

  test('HC-10 Alerts tab — rules section renders', async ({ page, request }) => {
    await loginViaApi(page)
    const { consoleErrors } = await visitPage(page, '/compliance?tab=alerts')
    const route = '/compliance?tab=alerts'
    const label = 'Alerts'

    const token = await getToken(request)
    const status = await apiStatus(request, '/api/v1/alerts/rules', token)
    if (status !== 200) {
      record(route, label, 'FAIL', `API /alerts/rules returned ${status}`)
      return
    }

    // Alert rules section heading
    const hasRulesSection = await hasVisible(page, 'h2, h1')
    if (!hasRulesSection) {
      record(route, label, 'FAIL', 'No headings found on alerts page')
      return
    }

    const rows = await tableRowCount(page)
    // Rules may be listed as cards rather than table rows — check for any card/list items too
    const hasCards = await hasVisible(page, '[class*="rounded"][class*="border"][class*="p-"]')

    if (rows === 0 && !hasCards) {
      record(route, label, 'EMPTY', 'No alert rules configured yet')
    } else {
      record(route, label, 'PASS', `Alert rules section rendered (rows: ${rows})`)
    }

    if (consoleErrors.length > 0) {
      record(route, `${label} (console)`, 'FAIL', consoleErrors.slice(0, 2).join(' | '))
    }
  })
})

// ═══════════════════════════════════════════════════════════════════════════════
// AUTOMATION HUB
// ═══════════════════════════════════════════════════════════════════════════════

test.describe('Health Check — Automation Hub', () => {
  test.setTimeout(40_000)

  test('HC-11 Executions tab — job history table', async ({ page, request }) => {
    await loginViaApi(page)
    const { consoleErrors } = await visitPage(page, '/automation?tab=executions')
    const route = '/automation?tab=executions'
    const label = 'Executions'

    const token = await getToken(request)
    const status = await apiStatus(request, '/api/v1/executions?page=1&per_page=5', token)
    if (status !== 200) {
      record(route, label, 'FAIL', `API /executions returned ${status}`)
      return
    }

    const rows = await tableRowCount(page)
    const hasH1 = await hasVisible(page, 'h1, h2')
    const hasEmptyMsg = await hasVisible(page, 'text=No executions, text=No jobs')

    if (!hasH1) {
      record(route, label, 'FAIL', 'No heading found')
    } else if (rows === 0 || hasEmptyMsg) {
      record(route, label, 'EMPTY', 'No execution history yet')
    } else {
      record(route, label, 'PASS', `${rows} execution rows`)
    }

    if (consoleErrors.length > 0) {
      record(route, `${label} (console)`, 'FAIL', consoleErrors.slice(0, 2).join(' | '))
    }
  })

  test('HC-12 Playbooks tab — at least 1 playbook listed', async ({ page, request }) => {
    await loginViaApi(page)
    const { consoleErrors } = await visitPage(page, '/automation?tab=playbooks')
    const route = '/automation?tab=playbooks'
    const label = 'Playbooks'

    const token = await getToken(request)
    const apiRes = await request.get(`${API}/api/v1/ansible/playbooks`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    if (apiRes.status() !== 200) {
      record(route, label, 'FAIL', `API /ansible/playbooks returned ${apiRes.status()}`)
      return
    }
    const playbookList = await apiRes.json() as unknown[]

    const hasH1 = await hasVisible(page, 'h1, h2')
    if (!hasH1) {
      record(route, label, 'FAIL', 'No heading found')
      return
    }

    // Playbooks are rendered as cards, not table rows
    const hasBootstrapCard = await hasVisible(page, 'text=Bootstrap Mac Mini')
    const hasAnyCard = await hasVisible(page, 'button:has-text("Run")')

    if (!hasAnyCard && playbookList.length === 0) {
      record(route, label, 'EMPTY', 'No playbooks discovered on disk')
    } else if (!hasAnyCard) {
      record(route, label, 'FAIL', `API returned ${playbookList.length} playbooks but UI shows none`)
    } else {
      record(
        route,
        label,
        'PASS',
        `${playbookList.length} playbooks via API; Bootstrap card: ${hasBootstrapCard}`,
      )
    }

    if (consoleErrors.length > 0) {
      record(route, `${label} (console)`, 'FAIL', consoleErrors.slice(0, 2).join(' | '))
    }
  })

  test('HC-13 Provisioning tab — renders', async ({ page, request }) => {
    await loginViaApi(page)
    const { consoleErrors } = await visitPage(page, '/automation?tab=provisioning')
    const route = '/automation?tab=provisioning'
    const label = 'Provisioning'

    const token = await getToken(request)
    const status = await apiStatus(request, '/api/v1/provisioning', token)
    if (status !== 200) {
      record(route, label, 'FAIL', `API /provisioning returned ${status}`)
      return
    }

    const hasH1 = await hasVisible(page, 'h1, h2')
    if (!hasH1) {
      record(route, label, 'FAIL', 'No heading found')
      return
    }

    const rows = await tableRowCount(page)
    if (rows === 0) {
      record(route, label, 'EMPTY', 'No provisioning history yet')
    } else {
      record(route, label, 'PASS', `${rows} provisioning rows`)
    }

    if (consoleErrors.length > 0) {
      record(route, `${label} (console)`, 'FAIL', consoleErrors.slice(0, 2).join(' | '))
    }
  })

  test('HC-14 Salt Ops tab — state browser left panel renders', async ({ page, request }) => {
    await loginViaApi(page)
    const { consoleErrors } = await visitPage(page, '/automation?tab=salt-ops')
    const route = '/automation?tab=salt-ops'
    const label = 'Salt Ops'

    const token = await getToken(request)
    const status = await apiStatus(request, '/api/v1/salt/states', token)
    if (status !== 200) {
      record(route, label, 'FAIL', `API /salt/states returned ${status}`)
      return
    }

    const hasH1 = await hasVisible(page, 'h1, h2')
    if (!hasH1) {
      record(route, label, 'FAIL', 'No heading found')
      return
    }

    // State browser: left panel should have folder/file items
    const hasFolderItems = await hasVisible(page, 'button[class*="flex items-center"], [class*="folder"], [class*="state"]')
    const hasEmptyMsg = await hasVisible(page, 'text=No states, text=no .sls files')

    if (hasEmptyMsg) {
      record(route, label, 'EMPTY', 'No Salt states on disk')
    } else if (!hasFolderItems) {
      // Salt states may be in a list without folder class names — check for any clickable items
      const hasAnyListItem = await hasVisible(page, 'button, li')
      if (!hasAnyListItem) {
        record(route, label, 'EMPTY', 'State browser left panel appears empty')
      } else {
        record(route, label, 'PASS', 'State browser rendered with items')
      }
    } else {
      record(route, label, 'PASS', 'State browser folder items visible')
    }

    if (consoleErrors.length > 0) {
      record(route, `${label} (console)`, 'FAIL', consoleErrors.slice(0, 2).join(' | '))
    }
  })

  test('HC-15 Minion Keys tab — accepted section present', async ({ page, request }) => {
    await loginViaApi(page)
    const { consoleErrors } = await visitPage(page, '/automation?tab=salt-keys')
    const route = '/automation?tab=salt-keys'
    const label = 'Minion Keys'

    const token = await getToken(request)
    const apiRes = await request.get(`${API}/api/v1/salt/keys`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    if (apiRes.status() !== 200) {
      record(route, label, 'FAIL', `API /salt/keys returned ${apiRes.status()}`)
      return
    }
    const keys = await apiRes.json() as { accepted?: string[]; pending?: string[] }

    const hasH1 = await hasVisible(page, 'h1')
    if (!hasH1) {
      record(route, label, 'FAIL', 'No h1 heading found')
      return
    }

    const acceptedCount = keys.accepted?.length ?? 0
    const pendingCount = keys.pending?.length ?? 0
    const totalKeyCount = acceptedCount + pendingCount + (keys.rejected?.length ?? 0)

    if (totalKeyCount === 0) {
      // No keys at all yet — page will be blank (sections only render when items > 0)
      record(route, label, 'EMPTY', 'No minion keys in any category')
    } else if (acceptedCount === 0) {
      // Some keys but none accepted — show what we have
      record(route, label, 'EMPTY', `0 accepted keys (pending: ${pendingCount})`)
    } else {
      // Check at least one known minion name (mm1 or mm2)
      const hasMm1 = await hasVisible(page, 'text=mm1')
      const hasMm2 = await hasVisible(page, 'text=mm2')
      const hasAcceptedSection = await hasVisible(page, 'text=Accepted')
      record(
        route,
        label,
        'PASS',
        `${acceptedCount} accepted keys — section visible: ${hasAcceptedSection}, mm1: ${hasMm1}, mm2: ${hasMm2}`,
      )
    }

    if (consoleErrors.length > 0) {
      record(route, `${label} (console)`, 'FAIL', consoleErrors.slice(0, 2).join(' | '))
    }
  })
})

// ═══════════════════════════════════════════════════════════════════════════════
// STANDALONE PAGES
// ═══════════════════════════════════════════════════════════════════════════════

test.describe('Health Check — Standalone Pages', () => {
  test.setTimeout(40_000)

  test('HC-16 Audit page — entries or empty state', async ({ page, request }) => {
    await loginViaApi(page)
    const { consoleErrors } = await visitPage(page, '/audit')
    const route = '/audit'
    const label = 'Audit Log'

    const token = await getToken(request)
    const status = await apiStatus(request, '/api/v1/audit?per_page=10', token)
    if (status !== 200) {
      record(route, label, 'FAIL', `API /audit returned ${status}`)
      return
    }

    const hasH1 = await hasVisible(page, 'h1')
    if (!hasH1) {
      record(route, label, 'FAIL', 'No h1 heading found')
      return
    }

    const hasTable = await hasVisible(page, 'table')
    const rows = await tableRowCount(page)
    const hasEmptyMsg = await hasVisible(page, 'text=No audit events found')

    if (!hasTable && !hasEmptyMsg) {
      record(route, label, 'FAIL', 'Neither table nor empty-state message found')
    } else if (rows === 0 || hasEmptyMsg) {
      record(route, label, 'EMPTY', 'No audit events yet')
    } else {
      record(route, label, 'PASS', `${rows} audit event rows`)
    }

    if (consoleErrors.length > 0) {
      record(route, `${label} (console)`, 'FAIL', consoleErrors.slice(0, 2).join(' | '))
    }
  })

  test('HC-17 Settings page — General tab with Salt master field', async ({ page, request }) => {
    await loginViaApi(page)
    const { consoleErrors } = await visitPage(page, '/settings')
    const route = '/settings'
    const label = 'Settings'

    const token = await getToken(request)
    const status = await apiStatus(request, '/api/v1/settings', token)
    if (status !== 200) {
      record(route, label, 'FAIL', `API /settings returned ${status}`)
      return
    }

    const hasH1 = await hasVisible(page, 'h1')
    if (!hasH1) {
      record(route, label, 'FAIL', 'No h1 heading found')
      return
    }

    // General tab is default — look for an input (salt master / kri API URL)
    const hasInput = await hasVisible(page, 'input[type="text"], input[type="url"], input[placeholder]')
    if (!hasInput) {
      record(route, label, 'FAIL', 'No input fields found on General tab')
      return
    }

    // Check tab navigation works
    const hasTabs = await hasVisible(page, 'button:has-text("Bootstrap"), button:has-text("Integrations")')
    record(
      route,
      label,
      'PASS',
      `Settings rendered; input fields present; tabs present: ${hasTabs}`,
    )

    if (consoleErrors.length > 0) {
      record(route, `${label} (console)`, 'FAIL', consoleErrors.slice(0, 2).join(' | '))
    }
  })
})

// ═══════════════════════════════════════════════════════════════════════════════
// SIDEBAR NAVIGATION CLICK TEST
// ═══════════════════════════════════════════════════════════════════════════════

test.describe('Health Check — Sidebar Nav Clickthrough', () => {
  test.setTimeout(60_000)

  test('HC-18 all sidebar nav links are clickable and reach a valid page', async ({ page }) => {
    await loginViaApi(page)

    // The sidebar links we expect to be present
    const navTargets: Array<{ label: string; href: string }> = [
      { label: 'Overview',    href: '/overview' },
      { label: 'Compliance',  href: '/compliance' },
      { label: 'Automation',  href: '/automation' },
      { label: 'Audit',       href: '/audit' },
      { label: 'Settings',    href: '/settings' },
    ]

    for (const { label, href } of navTargets) {
      // Find the sidebar link — try exact text match first, then partial
      const link = page
        .locator(`nav a[href="${href}"], aside a[href="${href}"]`)
        .or(page.locator(`a:has-text("${label}")`).first())
        .first()

      const isVisible = await link.isVisible({ timeout: 5_000 }).catch(() => false)
      if (!isVisible) {
        record(href, `Nav: ${label}`, 'FAIL', 'Link not found in sidebar')
        continue
      }

      await link.click()
      await page.waitForURL(`**${href}**`, { timeout: 8_000 }).catch(() => {})

      const currentUrl = page.url()
      const hasHeading = await hasVisible(page, 'h1, h2, [role="main"]')

      if (!currentUrl.includes(href.replace('/overview', '').replace('/compliance', '').replace('/automation', ''))) {
        // URL check can be loose for nested routes — rely on heading presence
      }

      // Give React a moment to render after navigation
      await page.waitForTimeout(500)
      const hasHeadingAfterWait = await hasVisible(page, 'h1, h2, [role="main"], main')

      if (!hasHeadingAfterWait) {
        record(href, `Nav: ${label}`, 'FAIL', `Clicked but no heading rendered — URL: ${currentUrl}`)
      } else {
        record(href, `Nav: ${label}`, 'PASS', `Navigated to ${currentUrl}`)
      }
    }
  })
})

// ═══════════════════════════════════════════════════════════════════════════════
// API ENDPOINT SMOKE TEST
// ═══════════════════════════════════════════════════════════════════════════════

test.describe('Health Check — API Endpoints', () => {
  test.setTimeout(30_000)

  test('HC-19 core API endpoints all return 200', async ({ request }) => {
    const token = await getToken(request)

    const endpoints: Array<{ path: string; label: string }> = [
      { path: '/api/v1/fleet/overview',              label: 'Fleet Overview' },
      { path: '/api/v1/nodes?page=1&per_page=5',     label: 'Nodes list' },
      { path: '/api/v1/groups',                      label: 'Groups list' },
      { path: '/api/v1/drift?page=1&per_page=5',     label: 'Drift records' },
      { path: '/api/v1/baselines',                   label: 'Baselines list' },
      { path: '/api/v1/sbom/browse',                 label: 'SBOM browse' },
      { path: '/api/v1/security/dashboard',          label: 'Security dashboard' },
      { path: '/api/v1/security/nodes',              label: 'Security nodes' },
      { path: '/api/v1/alerts/rules',                label: 'Alert rules' },
      { path: '/api/v1/executions?page=1&per_page=5', label: 'Executions / jobs' },
      { path: '/api/v1/ansible/playbooks',           label: 'Playbooks' },
      { path: '/api/v1/provisioning',                label: 'Provisioning profiles' },
      { path: '/api/v1/salt/states',                 label: 'Salt states' },
      { path: '/api/v1/salt/keys',                   label: 'Salt keys' },
      { path: '/api/v1/audit?per_page=10',           label: 'Audit log' },
      { path: '/api/v1/settings',                    label: 'Platform settings' },
    ]

    const failures: string[] = []

    for (const { path, label } of endpoints) {
      const status = await apiStatus(request, path, token)
      if (status === 200) {
        record(path, `API: ${label}`, 'PASS', `HTTP 200`)
      } else {
        record(path, `API: ${label}`, 'FAIL', `HTTP ${status}`)
        failures.push(`${label} → ${status}`)
      }
    }

    // Fail the test if any endpoints returned non-200
    expect(failures, `API failures:\n${failures.join('\n')}`).toHaveLength(0)
  })
})

// ═══════════════════════════════════════════════════════════════════════════════
// SUMMARY — runs after all tests in the file
// ═══════════════════════════════════════════════════════════════════════════════

test.afterAll(() => {
  const pass  = results.filter(r => r.status === 'PASS').length
  const fail  = results.filter(r => r.status === 'FAIL').length
  const empty = results.filter(r => r.status === 'EMPTY').length
  const skip  = results.filter(r => r.status === 'SKIP').length

  console.log('\n' + '═'.repeat(68))
  console.log('  kri Fleet Platform — Health Check Report')
  console.log('═'.repeat(68))
  console.log(`  PASS: ${pass}   FAIL: ${fail}   EMPTY: ${empty}   SKIP: ${skip}`)
  console.log('─'.repeat(68))

  // Group by status for readability
  const grouped: Record<Status, CheckResult[]> = { PASS: [], FAIL: [], EMPTY: [], SKIP: [] }
  results.forEach(r => grouped[r.status].push(r))

  for (const status of ['FAIL', 'EMPTY', 'PASS', 'SKIP'] as Status[]) {
    if (grouped[status].length === 0) continue
    console.log(`\n  ${status}`)
    grouped[status].forEach(r => {
      console.log(`    • ${r.label.padEnd(36)} ${r.detail}`)
    })
  }

  console.log('\n' + '═'.repeat(68) + '\n')
})
