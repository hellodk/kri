# kri — Test Cases

> Version: 0.1.0 | Platform: macOS Fleet Management  
> Covers: Authentication · Fleet · Nodes · Bootstrap · Groups · Drift · Baselines · SBOM · Playbooks · Settings · Search

---

## Legend

| Column | Meaning |
|--------|---------|
| **ID** | Unique test ID |
| **Priority** | P1 = must pass before release · P2 = important · P3 = nice-to-have |
| **Type** | Manual (M) · API (A) · Unit (U) |

---

## CI Status
- Unit tests: run on every PR (`pytest tests/unit/`)
- Integration tests: run on every PR (`pytest tests/integration/`)
- Coverage gate: 75% floor on `fleet_platform/services/`
- E2E: run manually against staging

Last updated: 2026-05-24

---

## 1. Authentication

| ID | Priority | Type | Title | Steps | Expected Result |
|----|----------|------|-------|-------|-----------------|
| AUTH-01 | P1 | M | Login with valid credentials | 1. Open `/login` 2. Enter `admin@fleet.local` / `changeme123` 3. Click Sign In | Redirected to `/fleet`, JWT stored in localStorage |
| AUTH-02 | P1 | M | Login fails with wrong password | 1. Enter valid email + wrong password 2. Click Sign In | Error toast shown, stays on login page |
| AUTH-03 | P1 | M | Login fails with unknown email | 1. Enter unknown email + any password | Error toast shown |
| AUTH-04 | P1 | A | JWT token returned on login | `POST /auth/login` with valid creds | `{ access_token, refresh_token, token_type: "bearer" }` |
| AUTH-05 | P1 | A | Protected route rejects missing token | `GET /api/v1/nodes` with no Authorization header | HTTP 401 |
| AUTH-06 | P1 | A | Refresh token rotates pair | `POST /auth/refresh` with valid refresh token | New access + refresh tokens; old refresh is revoked |
| AUTH-07 | P1 | A | Logout revokes refresh token | `POST /auth/logout` then try to refresh | `POST /auth/refresh` with old token returns 401 |
| AUTH-08 | P2 | A | Viewer cannot reach admin-only endpoint | Login as viewer, `PUT /api/v1/settings` | HTTP 403 |
| AUTH-09 | P2 | M | Session expires and redirects to login | Wait for token expiry (or clear localStorage) then navigate to any page | Redirected to `/login` |
| AUTH-10 | P2 | A | Rate limit on login endpoint | Send > 60 login requests per minute | HTTP 429 |

---

## 2. Fleet Dashboard

| ID | Priority | Type | Title | Steps | Expected Result |
|----|----------|------|-------|-------|-----------------|
| FLEET-01 | P1 | M | Dashboard loads stat cards | Navigate to `/fleet` | 4 stat cards: Total Nodes, Online, Offline/Stale, Avg Drift Score |
| FLEET-02 | P1 | M | Node table shows all nodes | Navigate to `/fleet` | Table lists nodes with Hostname, Status, OS, Drift, Last Seen, Tags |
| FLEET-03 | P1 | M | Status filter — Online | Select "Online" from Status dropdown | Table shows only online nodes |
| FLEET-04 | P1 | M | Status filter — Offline | Select "Offline" | Table shows only offline nodes |
| FLEET-05 | P1 | M | Status filter — All | Select "All" | Table shows all nodes |
| FLEET-06 | P2 | M | Per-page selector changes row count | Change per-page from 50 to 25 | Table shows 25 rows, "Showing 1–25 of N" |
| FLEET-07 | P2 | M | Pagination — next page | Click "Next →" | Table advances to page 2, URL or state updates |
| FLEET-08 | P1 | M | Click hostname → Node Detail | Click a node's hostname link | Navigates to `/nodes/{id}` |
| FLEET-09 | P2 | M | System tags shown in blue | Node has Salt-populated tags (hostname, ip, arch) | Tags shown with blue background and ⊙ indicator |
| FLEET-10 | P2 | M | User tags shown in gray | Node has manually added tags | Tags shown with gray background and × remove button |
| FLEET-11 | P1 | M | Empty state shows onboarding CTA | Fleet has 0 nodes | Shows "No nodes in your fleet yet" + "Bootstrap your first node →" button |
| FLEET-12 | P1 | A | Fleet overview API returns counts | `GET /api/v1/fleet/overview` | `{ total_nodes, online, stale, offline, unknown, avg_drift_score }` |
| FLEET-13 | P1 | A | Node list paginates correctly | `GET /api/v1/nodes?page=2&per_page=10` | Returns correct slice of nodes |
| FLEET-14 | P2 | A | Node list filters by status | `GET /api/v1/nodes?status=online` | Returns only online nodes |

---

## 3. Node Detail

| ID | Priority | Type | Title | Steps | Expected Result |
|----|----------|------|-------|-------|-----------------|
| NODE-01 | P1 | M | Node detail loads header | Navigate to `/nodes/{id}` | Shows hostname, StatusBadge, DriftBadge, IP, Last Seen |
| NODE-02 | P1 | M | Overview tab — hardware card | Click node, stay on Overview tab | Model, CPU Cores, RAM, Storage displayed |
| NODE-03 | P1 | M | Overview tab — OS card | Overview tab | OS version, build, First Seen date |
| NODE-04 | P1 | M | Overview tab — bootstrap status card hidden for unregistered | Node has `bootstrap_status = unregistered` | Bootstrap Status card is NOT shown in overview |
| NODE-05 | P1 | M | Overview tab — bootstrap status shown after bootstrap | Node has `bootstrap_status = completed` | Bootstrap Status card shows with green "Completed" badge |
| NODE-06 | P1 | M | Cancel bootstrap button visible when running | Node has `bootstrap_status = bootstrapping` | "Cancel bootstrap" red button shown in Bootstrap Status card |
| NODE-07 | P1 | M | Cancel bootstrap resets status | Click "Cancel bootstrap" | Status changes to "Failed", toast "Bootstrap cancelled" |
| NODE-08 | P1 | M | View Ansible output expands | Click "View Ansible output" in Bootstrap Status card | Pre block expands showing ansible-runner stdout |
| NODE-09 | P1 | M | Tags — add user tag | Enter key="env", value="prod", click Add | Tag appears with gray badge, success toast "Tag added" |
| NODE-10 | P1 | M | Tags — add duplicate key fails | Add tag with same key as existing | Error toast from API |
| NODE-11 | P1 | M | Tags — remove user tag | Click × on a gray user tag | Tag disappears, toast "Tag removed" |
| NODE-12 | P1 | M | Tags — system tag has no remove button | View Salt-populated tag (blue) | No × button, shows ⊙ indicator |
| NODE-13 | P1 | A | Cannot delete system tag via API | `DELETE /api/v1/nodes/{id}/tags/hostname` | HTTP 403 "auto-populated by Salt and cannot be deleted" |
| NODE-14 | P1 | A | Cannot overwrite system tag via API | `POST /api/v1/nodes/{id}/tags` with `key=hostname` | HTTP 403 |
| NODE-15 | P2 | M | Drift tab — shows latest drift record | Click "Drift" tab | Shows drift score, severity, package/service breakdown |
| NODE-16 | P2 | M | Drift tab — compute drift | Click "Compute now" | Spinner, then updated drift data after ~3s |
| NODE-17 | P2 | M | SBOM tab — shows scan | Click "SBOM" tab | Shows scan date, component count, component table |
| NODE-18 | P2 | M | Executions tab — lists jobs | Click "Executions" tab | Table of execution history for this node |

---

## 4. Bootstrap

### 4.1 Single Node Bootstrap

| ID | Priority | Type | Title | Steps | Expected Result |
|----|----------|------|-------|-------|-----------------|
| BOOT-01 | P1 | M | Open Bootstrap modal from dashboard | Click "+ Bootstrap Node" on Fleet Dashboard | Modal opens with "Single node" / "Bulk" tabs |
| BOOT-02 | P1 | M | Preview playbook toggle | Click "▼ Preview bootstrap playbook" | Expands YAML content of `bootstrap_mac_mini.yml` |
| BOOT-03 | P1 | M | Minion ID autocomplete — existing node | Type minion ID of a known node | IP field auto-fills, shows "✓ Node found in fleet — IP pre-filled and locked" |
| BOOT-04 | P1 | M | IP field locked for existing node | Existing node found via minion ID lookup | IP input is grayed out, `readonly`, cannot be edited |
| BOOT-05 | P1 | M | IP field editable for new node | Type unknown minion ID (>=2 chars, no match) | IP field is editable, shows "New node — enter IP address below" |
| BOOT-06 | P1 | M | Stuck detection — already bootstrapping | Type minion ID of a node with `bootstrap_status=bootstrapping` | Form replaced with amber warning + "Cancel bootstrap" button |
| BOOT-07 | P1 | M | Cancel from stuck detection | In stuck view, click "Cancel bootstrap" | Status resets to failed, form returns |
| BOOT-08 | P1 | M | Submit bootstrap — queues job | Fill minion ID + IP, click "Bootstrap" | Status panel shows "Queued", job ID returned |
| BOOT-09 | P1 | M | Bootstrap status polls every 3s | Job is running (bootstrapping state) | Status updates automatically every 3 seconds |
| BOOT-10 | P1 | M | Bootstrap complete CTA | Bootstrap finishes successfully | Shows "Bootstrap complete" + "Go to Fleet Dashboard →" button |
| BOOT-11 | P1 | M | "Go to Fleet Dashboard" navigates | Click "Go to Fleet Dashboard →" | Modal closes, redirected to `/fleet` |
| BOOT-12 | P1 | M | View logs after bootstrap | Click "▼ View logs" | Log viewer opens with Ansible output tab and Salt pillar tab |
| BOOT-13 | P1 | M | Pillar tab shows SLS content | Click "Salt pillar" tab in log viewer | Shows raw YAML written to `/srv/salt/pillar/<minion_id>.sls` |
| BOOT-14 | P1 | M | Ansible logs auto-refresh while running | Open logs while bootstrap is running | Log content refreshes every 5 seconds |
| BOOT-15 | P1 | A | Bootstrap endpoint returns 202 | `POST /api/v1/ansible/bootstrap` with valid payload | `{ node_id, minion_id, job_id, bootstrap_status: "pending" }` |
| BOOT-16 | P1 | A | Bootstrap returns 409 if already running | Call bootstrap twice for same node while first is pending | HTTP 409 "Node is already being bootstrapped" |
| BOOT-17 | P1 | A | Bootstrap rate-limited | Send >10 bootstrap requests per minute | HTTP 429 |
| BOOT-18 | P1 | A | Invalid minion ID rejected | Minion ID with path traversal `../etc` | Bootstrap task sets node to failed with validation error |
| BOOT-19 | P1 | A | Cancel endpoint resets status | `POST /api/v1/ansible/bootstrap/{node_id}/cancel` | `{ bootstrap_status: "failed" }` |
| BOOT-20 | P2 | A | Cancel returns 409 if not running | Cancel a node with `bootstrap_status=completed` | HTTP 409 "nothing to cancel" |
| BOOT-21 | P2 | A | Log endpoint returns pillar + stdout | `GET /api/v1/ansible/bootstrap/{node_id}/logs` | `{ pillar, ansible_stdout, bootstrap_status, pillar_path }` |
| BOOT-22 | P2 | M | Ansible collection resolves offline | Run bootstrap with network disabled | `ansible.posix.authorized_key` resolves from bundled collection |

### 4.2 Bulk Bootstrap

| ID | Priority | Type | Title | Steps | Expected Result |
|----|----------|------|-------|-------|-----------------|
| BOOT-B01 | P1 | M | Switch to Bulk mode | Click "Bulk (multiple nodes)" tab | Shows textarea for multi-line input |
| BOOT-B02 | P1 | M | Parse valid input lines | Enter `mac-01  10.0.1.11\nmac-02  10.0.1.12` | Shows "2 hosts detected" below textarea |
| BOOT-B03 | P1 | M | Comment lines ignored | First line is `# comment` | Comment not counted as a host |
| BOOT-B04 | P1 | M | Extra tags parsed and shown | Line: `mac-01  10.0.1.11  serial=ABC123  location=rack-A` | After submit, job row shows serial=ABC123 / location=rack-A tags |
| BOOT-B05 | P1 | M | All jobs launched in parallel | Submit 5 hosts | All 5 show "Queued" simultaneously, not sequentially |
| BOOT-B06 | P1 | M | Status table polls per-job | Each row polls its job | Each row updates independently as jobs progress |
| BOOT-B07 | P2 | M | Failed job shown in red | One node's bootstrap fails (wrong IP) | That row shows "Failed" in red, others still running |

---

## 5. Groups

| ID | Priority | Type | Title | Steps | Expected Result |
|----|----------|------|-------|-------|-----------------|
| GRP-01 | P1 | M | Groups list page loads | Navigate to `/groups` | Table of groups with name, type, member count |
| GRP-02 | P1 | M | Create static group | Click "New Group", enter name, type=static, submit | Group appears in list, type badge shows "static" |
| GRP-03 | P1 | M | Create dynamic group with predicate | Create group with type=dynamic, enter predicate JSON | Group appears with "dynamic" purple badge |
| GRP-04 | P1 | M | Click group → Group Detail | Click group name | Navigates to `/groups/{id}`, shows member table |
| GRP-05 | P1 | M | Group type tooltip — dynamic | Hover over "dynamic ℹ" badge | Tooltip explains dynamic groups auto-resolve membership |
| GRP-06 | P1 | M | Static group — add node | Click "+ Add node", select node from dropdown, click Add | Node appears in member table, member count increments |
| GRP-07 | P1 | M | Static group — remove node | Click "Remove" on a member row | Node removed from table, member count decrements |
| GRP-08 | P1 | M | Dynamic group — no add/remove button | View a dynamic group | No "+ Add node" button, no Remove column |
| GRP-09 | P2 | M | Dynamic group tooltip explains no manual edit | Hover "dynamic ℹ" badge | "membership is resolved automatically from a predicate. Nodes cannot be added or removed manually." |
| GRP-10 | P1 | A | Add member — static group | `POST /api/v1/groups/{id}/members` with `{node_id}` | HTTP 200, member_count increments |
| GRP-11 | P1 | A | Remove member | `DELETE /api/v1/groups/{id}/members/{node_id}` | HTTP 204 |
| GRP-12 | P2 | A | Group member list paginates | `GET /api/v1/groups/{id}/nodes?page=1&per_page=5` | Returns paginated node list |

---

## 6. Drift & Baselines

### 6.1 Drift Explorer

| ID | Priority | Type | Title | Steps | Expected Result |
|----|----------|------|-------|-------|-----------------|
| DRIFT-01 | P1 | M | Drift page loads | Navigate to `/drift` | Table of nodes with drift summary |
| DRIFT-02 | P1 | M | Filter by severity | Select "high" from severity dropdown | Only high-severity nodes shown |
| DRIFT-03 | P2 | M | Node drift history chart | On Node Detail > Drift tab | Line chart showing drift score over 30 days |
| DRIFT-04 | P1 | A | Compute drift for node | `POST /api/v1/drift/{node_id}/compute` | `{ status: "queued" }`, Celery task enqueued |
| DRIFT-05 | P1 | A | Latest drift record returns breakdown | `GET /api/v1/drift/{node_id}/latest` | `{ drift_score, severity, missing_packages, extra_packages, version_mismatches }` |

### 6.2 Baselines

| ID | Priority | Type | Title | Steps | Expected Result |
|----|----------|------|-------|-------|-----------------|
| BASE-01 | P1 | M | Baselines page loads | Navigate to `/baselines` | Table of baselines or empty state CTA |
| BASE-02 | P1 | M | Create global baseline | Click "+ New Baseline", name="Test", target=All nodes, keep starter JSON, click Create | Baseline appears in list with green "All nodes" badge |
| BASE-03 | P1 | M | Create group baseline | Create baseline with target=Group, select a group | Baseline appears with purple "Group" badge |
| BASE-04 | P1 | M | Create node baseline | Create baseline with target=Node, select a node | Baseline appears with blue "Node" badge |
| BASE-05 | P1 | M | JSON validation — invalid JSON | Enter `{invalid` in state editor | Red border, error message, Create button disabled |
| BASE-06 | P1 | M | JSON validation — valid JSON | Enter valid JSON | No error, Create button enabled |
| BASE-07 | P1 | M | View baseline detail | Click "View" on a baseline | Modal shows name, target, version, formatted JSON state |
| BASE-08 | P1 | M | Empty state CTA | No baselines exist | Shows "Create your first baseline" button |
| BASE-09 | P1 | A | Create baseline via API | `POST /api/v1/baselines` with valid payload | Returns `BaselineResponse` with id, version=1 |
| BASE-10 | P1 | A | List baselines | `GET /api/v1/baselines` | Paginated list of baselines |
| BASE-11 | P2 | A | Get single baseline | `GET /api/v1/baselines/{id}` | Returns full baseline with `state_json` |
| BASE-12 | P2 | M | Explanation text is readable | Load Baselines page | Info banner explains drift scoring and target precedence |

---

## 7. Playbooks

| ID | Priority | Type | Title | Steps | Expected Result |
|----|----------|------|-------|-------|-----------------|
| PLAY-01 | P1 | M | Playbooks page loads | Navigate to `/playbooks` | Cards for each `.yml` in `playbooks/` and roles in `playbooks/roles/` |
| PLAY-02 | P1 | M | Bootstrap playbook card shown | Default install has `bootstrap_mac_mini.yml` | Card titled "Bootstrap Mac Mini into kri fleet" |
| PLAY-03 | P1 | M | Playbook default vars displayed | Card for playbook with vars: section | Variable key=value pairs shown in "Variables" section of card |
| PLAY-04 | P1 | M | Role cards shown separately | `playbooks/roles/` has subdirectories | Roles in separate "Roles" section below Playbooks |
| PLAY-05 | P1 | M | Run button → confirmation dialog | Click "Run" on any playbook | Confirmation dialog: "Run playbook? [name] will run against real infrastructure." |
| PLAY-06 | P1 | M | Cancel confirmation | Click Cancel in dialog | Dialog closes, playbook not run |
| PLAY-07 | P1 | M | Continue → Run modal opens | Click Continue | Run Playbook modal opens (wider, with step sections) |
| PLAY-08 | P1 | M | Run modal — target type selector | In Run modal, select "Single node" or "Group" | Dropdown changes to show nodes or groups respectively |
| PLAY-09 | P1 | M | Variable editor pre-fills defaults | Playbook has vars | All default_var keys shown as editable inputs |
| PLAY-10 | P1 | M | System vars highlighted amber | Variable key is `ansible_become` | Amber border + "⚠ system var" label |
| PLAY-11 | P1 | M | Submit — job queued | Select target, click "Run Playbook" | Shows "Queued" status with spinner |
| PLAY-12 | P1 | M | Status polls every 3s | Job running | Status badge updates; spinner visible |
| PLAY-13 | P1 | M | stdout shown after completion | Job completes | Ansible output displayed in dark monospace block |
| PLAY-14 | P1 | M | Exit code shown | Job done | "Exit code: 0" or "Exit code: 1" shown |
| PLAY-15 | P1 | M | Close runs in background | Click "Close (runs in background)" while running | Modal closes, job continues, status accessible via Ansible jobs endpoint |
| PLAY-16 | P1 | A | List playbooks | `GET /api/v1/ansible/playbooks` | Array of `{ filename, name, description, entry_type, default_vars }` |
| PLAY-17 | P1 | A | Path traversal rejected | `POST /api/v1/ansible/playbooks/run` with `playbook: "../../etc/passwd"` | HTTP 404 |
| PLAY-18 | P1 | A | Get playbook content | `GET /api/v1/ansible/playbooks/content?filename=bootstrap_mac_mini.yml` | `{ filename, content }` with raw YAML |
| PLAY-19 | P1 | A | Run job status endpoint | `GET /api/v1/ansible/jobs/{job_id}` | `{ id, status, stdout, rc, target_label }` |
| PLAY-20 | P2 | A | Unknown job returns 404 | `GET /api/v1/ansible/jobs/00000000-...` | HTTP 404 |
| PLAY-21 | P2 | M | Variable changes committed to git | Run playbook with modified variables | `playbooks/host_vars/<hostname>.yml` or `group_vars/<name>.yml` created/updated |

---

## 8. Platform Settings

| ID | Priority | Type | Title | Steps | Expected Result |
|----|----------|------|-------|-------|-----------------|
| SET-01 | P1 | M | Settings page loads | Navigate to `/settings` | Shows Salt Master, SSH Credentials, Controller Key, Playbooks Dir, Pillar Dir, Ansible Endpoint sections |
| SET-02 | P1 | M | Required / Optional dividers visible | Load Settings page | "Required" divider above Salt Master, "Optional / Advanced" above Playbooks Dir |
| SET-03 | P1 | M | Save Salt master address | Enter "10.0.0.1", click Save | Toast "Settings saved"; re-opening page shows "10.0.0.1" |
| SET-04 | P1 | M | Save SSH username | Enter username, click Save | Saved; re-loaded on next page open |
| SET-05 | P1 | M | Save SSH password (encrypted) | Enter password, click Save | Password field clears after save; never shown in GET response |
| SET-06 | P1 | M | Eye icon toggles password visibility | Click eye icon next to SSH password field | Field switches between `type=password` and `type=text` |
| SET-07 | P2 | M | Controller public key shows after first save | First save generates keypair | Public key shown in "Controller SSH Public Key" card |
| SET-08 | P2 | M | Copy key button works | Click "Copy" next to public key | Clipboard contains the key content, toast "Copied" |
| SET-09 | P2 | M | Playbooks directory configurable | Enter custom path, save | Playbooks discovered from that path on next API call |
| SET-10 | P2 | M | Pillar directory configurable | Enter custom path, save | Bootstrap writes pillar to that path |
| SET-11 | P2 | M | Ansible endpoint optional | Leave blank | Bootstrap uses local ansible-runner |
| SET-12 | P1 | A | GET settings — never returns password | `GET /api/v1/settings` | `ssh_bootstrap_password` is always `null` in response |
| SET-13 | P1 | A | PUT settings — partial update | `PUT /api/v1/settings` with only `salt_master_address` | Only that field updated; others unchanged |
| SET-14 | P1 | A | Settings admin-only | Call as viewer role | HTTP 403 |

---

## 9. Search

| ID | Priority | Type | Title | Steps | Expected Result |
|----|----------|------|-------|-------|-----------------|
| SRCH-01 | P1 | M | Search triggers at 3 chars | Type "mac" in TopBar search | Dropdown opens with matching nodes |
| SRCH-02 | P1 | M | Empty state shown on no match | Type "zzz" with no matching nodes | Dropdown shows "No nodes found" |
| SRCH-03 | P1 | M | Loading state shown | Type query before response returns | Dropdown shows "Searching…" |
| SRCH-04 | P1 | M | Click result navigates to node | Click a search result | Navigates to `/nodes/{id}` |
| SRCH-05 | P1 | M | Dropdown closes on navigation | Click result | Dropdown closes |
| SRCH-06 | P2 | M | Dropdown closes on blur | Click outside search | Dropdown closes |
| SRCH-07 | P1 | A | Search by minion ID | `GET /api/v1/search?q=mac-mini-01` | Returns matching nodes |
| SRCH-08 | P1 | A | Search by hostname partial | `GET /api/v1/search?q=mac` | Returns nodes with "mac" in hostname/minion_id |

---

## 10. System Tags (Auto-population)

| ID | Priority | Type | Title | Steps | Expected Result |
|----|----------|------|-------|-------|-----------------|
| STAG-01 | P1 | A | Grain ingest creates system tags | POST grains with `fqdn`, `cpuarch`, `productname` | Tags `hostname`, `arch`, `model` created with `source=system` |
| STAG-02 | P1 | A | Second ingest updates system tags | Ingest with different OS version | `macos_version` tag updated |
| STAG-03 | P1 | A | Serial tag created from grain | Ingest with `serialnumber=ABC123` | Tag `serial=ABC123` created |
| STAG-04 | P1 | A | System tag source is "system" | After ingest, GET node tags | All auto-populated tags have `source: "system"` |
| STAG-05 | P1 | A | User tag not overwritten by ingest | Create tag `hostname=custom` (user), then ingest | API rejects with 403 (user-created `hostname` tag blocks it) |
| STAG-06 | P1 | M | System tags show blue in UI | Fleet Dashboard after grain ingest | `hostname`, `ip`, `arch` tags shown in brand blue with ⊙ |
| STAG-07 | P1 | M | User tags show gray with × | Manually added tag | Gray badge with × remove button |
| STAG-08 | P2 | M | Tags legend visible | View Node Detail Tags card | "auto (Salt)" + "manual" legend shown in card header |

---

## 11. Navigation & Layout

| ID | Priority | Type | Title | Steps | Expected Result |
|----|----------|------|-------|-------|-----------------|
| NAV-01 | P1 | M | All sidebar links navigate correctly | Click each icon: Fleet, Drift, SBOM, Groups, Executions, Playbooks, Baselines, Audit, Settings | Each navigates to correct page without error |
| NAV-02 | P2 | M | Sidebar collapsed mode — tooltips | Collapse sidebar (toggle), hover over icons | Tooltip with label appears on hover |
| NAV-03 | P1 | M | Active link highlighted | Current page link | Active icon has blue/brand highlight |
| NAV-04 | P2 | M | Sidebar expand/collapse | Click toggle button | Sidebar expands (shows labels) or collapses (icons only) |
| NAV-05 | P1 | M | Back navigation from Node Detail | Click "← Fleet" breadcrumb | Returns to Fleet Dashboard |
| NAV-06 | P1 | M | Back navigation from Group Detail | Click "← Groups" breadcrumb | Returns to Groups list |

---

## 12. Health & Reliability

| ID | Priority | Type | Title | Steps | Expected Result |
|----|----------|------|-------|-------|-----------------|
| HLTH-01 | P1 | A | Health ready endpoint | `GET /health/ready` | `{ status: "ready", checks: { database: "ok", redis: "ok" } }` |
| HLTH-02 | P1 | A | Health degrades when DB down | Stop postgres, call `/health/ready` | `{ status: "degraded" }`, HTTP 503 |
| HLTH-03 | P2 | A | SBOM ingest cap enforced | POST SBOM > 50 MB | HTTP 413 |
| HLTH-04 | P2 | A | Ingest rate limited | Send > 60 grain ingests per minute | HTTP 429 |
| HLTH-05 | P1 | M | kri.sh start brings all services up | Run `./scripts/kri.sh start` | API :8000, frontend :5173, Celery all healthy |
| HLTH-06 | P1 | M | kri.sh stop cleanly shuts down | Run `./scripts/kri.sh stop` | All services stopped, PID files removed |
| HLTH-07 | P1 | M | kri.sh status shows running services | Run `./scripts/kri.sh status` | Shows ✓ api, ✓ worker, ✓ frontend with PIDs |
| HLTH-08 | P2 | M | kri.sh logs tails correct service | Run `./scripts/kri.sh logs worker` | Tails `.kri-logs/worker.log` |

---

## 13. Security

| ID | Priority | Type | Title | Steps | Expected Result |
|----|----------|------|-------|-------|-----------------|
| SEC-01 | P1 | A | Minion ID with path traversal rejected | Bootstrap with `minion_id=../etc/passwd` | Returns `{ reason: "Invalid minion ID" }` |
| SEC-02 | P1 | A | Playbook path traversal rejected | Run playbook with filename `../../etc/shadow` | HTTP 404 — not in discovered allowlist |
| SEC-03 | P1 | A | System tag cannot be modified | `POST /nodes/{id}/tags` with key matching a system tag | HTTP 403 |
| SEC-04 | P1 | A | System tag cannot be deleted | `DELETE /nodes/{id}/tags/hostname` | HTTP 403 |
| SEC-05 | P1 | A | Bootstrap rate limited | > 10 requests/minute | HTTP 429 |
| SEC-06 | P2 | A | Viewer cannot create baseline | POST `/api/v1/baselines` as viewer | HTTP 403 |
| SEC-07 | P2 | A | Viewer cannot run playbook | POST `/api/v1/ansible/playbooks/run` as viewer | HTTP 403 |
| SEC-08 | P2 | A | SSH password never returned | GET `/api/v1/settings` | `ssh_bootstrap_password` is always `null` |
| SEC-09 | P2 | A | Ansible API token never returned | GET `/api/v1/settings` | `ansible_api_token` is always `null` |
| SEC-10 | P1 | A | Ansible collection resolves offline | Run with no internet | Collection loaded from `playbooks/collections/installed/` |

---

## Automated Test Commands

```bash
# Run full backend test suite
cd /home/dk/Documents/git/kri && source .venv/bin/activate
python -m pytest tests/ -v --no-header 2>&1 | tail -20

# Run only integration tests
python -m pytest tests/integration/ -v 2>&1 | tail -20

# Run only unit tests
python -m pytest tests/unit/ -v 2>&1 | tail -20

# Run specific test file
python -m pytest tests/integration/test_ansible_api.py -v

# Run specific test
python -m pytest tests/unit/test_ansible_validation.py::test_valid_minion_id -v

# TypeScript check
cd frontend && npx tsc --noEmit

# Production build
cd frontend && npm run build

# API smoke test (requires kri running)
TOKEN=$(curl -s -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@fleet.local","password":"changeme123"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

curl -s -H "Authorization: Bearer $TOKEN" http://localhost:8000/health/ready
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/fleet/overview | python3 -m json.tool
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/ansible/playbooks | python3 -m json.tool
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/baselines | python3 -m json.tool
```

---

## 14. User Journeys

End-to-end flows that span multiple features. Each journey should be tested as a complete sequence without resetting state between steps.

---

### Journey 1: New Operator Onboarding — Zero to First Node

**Persona:** IT admin who has just installed kri for the first time. No nodes, no settings configured.

| ID | Priority | Type | Step | Actions | Expected Result |
|----|----------|------|------|---------|-----------------|
| JRN1-01 | P1 | M | Log in | Open `/login`, enter `admin@fleet.local` / `changeme123` | Redirected to `/fleet`. Stat cards show 0 for everything. Empty state shows "No nodes in your fleet yet" |
| JRN1-02 | P1 | M | Configure settings | Navigate to `/settings`. Enter Salt master IP, SSH username, SSH password. Click Save | Toast "Settings saved". Controller SSH public key appears in the card |
| JRN1-03 | P1 | M | Copy controller key | Click "Copy" next to the public key | Clipboard contains the RSA public key (used to verify bootstrap will authorise it on Mac Minis) |
| JRN1-04 | P1 | M | Open Bootstrap modal | Click "+ Bootstrap Node" on Fleet Dashboard | Modal opens. "Single node" tab is active |
| JRN1-05 | P1 | M | Preview the playbook | Click "▼ Preview bootstrap playbook" | YAML content expands — operator reviews what will run |
| JRN1-06 | P1 | M | Enter new node details | Type minion ID "mac-mini-01", confirm "New node" hint, enter IP "10.0.1.11" | IP field editable, no auto-fill |
| JRN1-07 | P1 | M | Submit bootstrap | Click "Bootstrap" | Status panel shows "Queued", then transitions to "Running…" with spinner |
| JRN1-08 | P1 | M | View live logs | Click "▼ View logs" | Ansible output tab shows task-by-task progress |
| JRN1-09 | P1 | M | Bootstrap completes | Wait for job to finish | Status shows "Done ✓", completion message, "Go to Fleet Dashboard →" button appears |
| JRN1-10 | P1 | M | Navigate to fleet | Click "Go to Fleet Dashboard →" | Fleet page shows 1 node: mac-mini-01, status = stale or unknown (Salt not yet connected) |
| JRN1-11 | P2 | M | Salt minion connects | Mac Mini salt-minion starts and reports grains | After ~60s, node appears/updates with status=online, system tags populated (hostname, ip, arch, model, etc.) |
| JRN1-12 | P2 | M | Verify system tags | Click on the node | System tags shown in blue: hostname, ip, arch, model, macos_version |

---

### Journey 2: Bootstrapping a Fleet of 10 Mac Minis in One Shot

**Persona:** IT admin rolling out 10 identical Mac Minis simultaneously.

| ID | Priority | Type | Step | Actions | Expected Result |
|----|----------|------|------|---------|-----------------|
| JRN2-01 | P1 | M | Open Bootstrap modal, Bulk tab | Click "+ Bootstrap Node" → "Bulk (multiple nodes)" | Textarea with placeholder format shown |
| JRN2-02 | P1 | M | Paste host list | Enter 10 lines, each: `mac-mini-NN  10.0.1.NN  serial=XXXX  location=rack-A` | "10 hosts detected · extra tags will be applied after bootstrap" |
| JRN2-03 | P1 | M | Submit all | Click "Bootstrap 10 nodes" | Button shows "Launching…" briefly, then status table appears |
| JRN2-04 | P1 | M | All jobs launched in parallel | Observe status table | All 10 rows show "Queued" simultaneously (not sequentially) |
| JRN2-05 | P1 | M | Jobs progress independently | Watch status table | Each row updates independently; some may complete before others |
| JRN2-06 | P1 | M | Extra tags shown per row | Inspect rows | Each row shows serial= and location= tag badges |
| JRN2-07 | P2 | M | Close modal, jobs continue | Click "Close (jobs run in background)" while some are still running | Modal closes; Fleet Dashboard node count updates as nodes come online |
| JRN2-08 | P2 | M | Verify all nodes in fleet | After all bootstraps complete, check Fleet Dashboard | 10+ nodes appear with online status after Salt minions connect |

---

### Journey 3: Detecting and Investigating a Drifted Node

**Persona:** Security engineer investigating why a Mac Mini has a high drift score.

| ID | Priority | Type | Step | Actions | Expected Result |
|----|----------|------|------|---------|-----------------|
| JRN3-01 | P1 | M | Define a baseline | Navigate to `/baselines`, click "+ New Baseline" | Create modal opens |
| JRN3-02 | P1 | M | Set baseline content | Name="macOS Standard", target=All nodes, set packages: salt >=3006, services: salt-minion running | JSON validates, Create enabled |
| JRN3-03 | P1 | M | Create baseline | Click "Create Baseline" | Toast "Baseline created", appears in list |
| JRN3-04 | P1 | M | Trigger drift compute | Go to Node Detail → Drift tab → click "Compute now" | Spinner, then drift record appears after ~3s |
| JRN3-05 | P1 | M | Review drift details | Inspect drift record | Shows drift_score, severity, missing_packages, extra_packages, version_mismatches |
| JRN3-06 | P2 | M | Navigate to Drift Explorer | Go to `/drift` | Table shows all nodes sorted by drift score descending |
| JRN3-07 | P2 | M | Filter high-drift nodes | Select severity="critical" | Only nodes with critical drift shown |
| JRN3-08 | P2 | M | Click node from drift explorer | Click a node's hostname | Navigates to that node's detail page, Drift tab |
| JRN3-09 | P2 | M | View drift history chart | Scroll down on Drift tab | Line chart shows drift score trend over 30 days |

---

### Journey 4: Running a Playbook Against a Group

**Persona:** Fleet admin pushing a config change to all production nodes.

| ID | Priority | Type | Step | Actions | Expected Result |
|----|----------|------|------|---------|-----------------|
| JRN4-01 | P1 | M | Create a group | Go to `/groups`, click "New Group", create static group "production" | Group appears in list |
| JRN4-02 | P1 | M | Add nodes to group | Click group → "+ Add node", add 3 nodes | Member count shows 3 |
| JRN4-03 | P1 | M | Navigate to Playbooks | Go to `/playbooks` | Playbook cards shown |
| JRN4-04 | P1 | M | Click Run | Click "Run" on a playbook card | Confirmation dialog appears |
| JRN4-05 | P1 | M | Confirm | Click "Continue" | Run Playbook modal opens |
| JRN4-06 | P1 | M | Select Group as target type | Click "Group" radio button | Dropdown changes to list groups |
| JRN4-07 | P1 | M | Select "production" group | Select from dropdown | Group selected |
| JRN4-08 | P1 | M | Review and modify variables | Check variable editor — modify any value if needed | Amber highlight on system vars |
| JRN4-09 | P1 | M | Run | Click "Run Playbook" | Job queued, status shows "Queued" → "Running…" |
| JRN4-10 | P1 | M | Ansible runs on all group members | Wait for completion | stdout shows tasks executed on all 3 nodes |
| JRN4-11 | P2 | M | Verify var file committed | Check git log | Commit "chore(kri): update ansible var files" with `group_vars/production.yml` |

---

### Journey 5: Cancelling a Stuck Bootstrap and Retrying

**Persona:** Operator who triggered a bootstrap that hasn't progressed in 10 minutes.

| ID | Priority | Type | Step | Actions | Expected Result |
|----|----------|------|------|---------|-----------------|
| JRN5-01 | P1 | M | Find stuck node | Navigate to `/nodes/{id}` for the stuck node | Bootstrap Status card shows "Running…" with spinner |
| JRN5-02 | P1 | M | Cancel from Node Detail | Click "Cancel bootstrap" in Bootstrap Status card | Confirmation toast "Bootstrap cancelled", status changes to "Failed" |
| JRN5-03 | P1 | M | Alternative: cancel via Bootstrap modal | Click "+ Bootstrap Node", type the stuck node's minion ID | Modal shows amber warning "Bootstrap already in progress" with Cancel button |
| JRN5-04 | P1 | M | Cancel via modal | Click "Cancel bootstrap" | Toast shown, form returns (can now re-submit) |
| JRN5-05 | P1 | M | Retry bootstrap | Enter IP, click "Bootstrap" | New job queued, bootstrap restarts |
| JRN5-06 | P2 | M | Check logs from previous attempt | After cancel, before retry: click "View logs" on previous run | Ansible stdout from the failed attempt shown |

---

### Journey 6: Inventory Management with Tags

**Persona:** IT admin tracking physical location and asset metadata for the fleet.

| ID | Priority | Type | Step | Actions | Expected Result |
|----|----------|------|------|---------|-----------------|
| JRN6-01 | P1 | M | System tags auto-appear after Salt connect | Node with active salt-minion | Hostname, IP, arch, model, serial tags appear automatically in blue |
| JRN6-02 | P1 | M | Add location tag | Node Detail → Tags → enter key="location", value="rack-A-slot-3" | Gray badge with × appears |
| JRN6-03 | P1 | M | Add environment tag | Enter key="env", value="production" | Gray badge appears |
| JRN6-04 | P1 | M | Try to overwrite system tag | Enter key="hostname", value="my-custom-name" | Error toast "Tag 'hostname' is auto-populated by Salt and cannot be modified" |
| JRN6-05 | P1 | M | Remove user tag | Click × on location tag | Tag removed |
| JRN6-06 | P2 | M | Filter fleet by tag | In Fleet Dashboard: type `env:production` in tag filter (if supported) OR use groups | Nodes with env=production shown |
| JRN6-07 | P2 | M | Bulk tag via bootstrap | In bulk bootstrap, add `location=rack-B` to all hosts | After bootstrap, all nodes have location=rack-B tag |

---

### Journey 7: SBOM Audit Workflow

**Persona:** Security engineer checking for vulnerable package versions.

| ID | Priority | Type | Step | Actions | Expected Result |
|----|----------|------|------|---------|-----------------|
| JRN7-01 | P2 | M | Navigate to SBOM Explorer | Go to `/sbom` | Table of recent SBOM scans |
| JRN7-02 | P2 | M | Search for a package | Enter package name in search | Nodes that have the package listed with version and scan date |
| JRN7-03 | P2 | M | Open node SBOM | Click on a node hostname | Navigates to Node Detail → SBOM tab |
| JRN7-04 | P2 | M | Browse components | SBOM tab shows component table | Name, version, type, licenses columns |
| JRN7-05 | P2 | M | Paginate components | Click "Next →" in component table | Next page of components loads |

---

## 15. Edge Cases

---

### 15.1 Bootstrap Edge Cases

| ID | Priority | Type | Title | Steps | Expected Result |
|----|----------|------|-------|-------|-----------------|
| EDGE-B01 | P1 | A | Bootstrap with no SSH credentials configured | Call bootstrap API before configuring Settings | Celery task runs, ansible fails gracefully — node status set to "failed", error includes "empty password" or SSH failure |
| EDGE-B02 | P1 | M | Bootstrap with wrong SSH password | Configure wrong password in Settings, bootstrap a real Mac Mini | Node status = failed, bootstrap_error shows SSH auth failure message |
| EDGE-B03 | P1 | A | Bootstrap with unreachable IP | Use IP that doesn't respond (e.g. 10.255.255.1) | Node status = failed, bootstrap_error shows "Connection refused" or timeout |
| EDGE-B04 | P1 | A | Concurrent bootstrap of same node | Send two bootstrap requests simultaneously | First returns 202, second returns 409 "already being bootstrapped" |
| EDGE-B05 | P1 | M | Bootstrap of already-bootstrapped node | Re-bootstrap a completed node | Form shows pre-filled IP (locked); on submit re-queues job, rotates auth token |
| EDGE-B06 | P1 | A | Minion ID with spaces | POST bootstrap with `minion_id="mac mini 01"` | Celery task returns `{ reason: "Invalid minion ID" }`, status set to failed |
| EDGE-B07 | P1 | A | Minion ID with path traversal | POST with `minion_id="../../../etc"` | Task returns `{ reason: "Invalid minion ID" }` |
| EDGE-B08 | P1 | A | Minion ID exceeds 128 chars | POST with 129-char minion ID | Task returns validation error |
| EDGE-B09 | P2 | M | Browser tab closed during bootstrap | Launch bootstrap, immediately close tab | Job continues in background; reopen app, check node status — shows completed or failed |
| EDGE-B10 | P2 | M | Page refresh during bootstrap | Launch bootstrap, press F5 | After refresh, bootstrap modal gone — node status visible via Fleet Dashboard → Node Detail |
| EDGE-B11 | P2 | A | Celery worker down during bootstrap | Stop Celery worker, submit bootstrap | Node stays in "pending" — no task picked up. When worker restarts, task resumes (or stays stuck requiring manual cancel) |
| EDGE-B12 | P2 | A | Bootstrap with Salt master not set | Leave `salt_master_address` blank, bootstrap | Playbook runs with `salt_master=localhost`; minion config points to 127.0.0.1 (documented behaviour) |
| EDGE-B13 | P1 | M | Bulk bootstrap with 1 invalid line | Mix valid lines with `invalid line no-ip-here` | 1 host parsed (no IP = not counted), only valid hosts bootstrapped |
| EDGE-B14 | P2 | M | Bulk bootstrap: one fails, others succeed | 5 hosts where 1 has wrong IP | 4 rows show "Done ✓", 1 shows "Failed" in red |
| EDGE-B15 | P2 | A | Cancel non-running bootstrap | POST cancel on node with `bootstrap_status=completed` | HTTP 409 "nothing to cancel" |

---

### 15.2 Node & Tag Edge Cases

| ID | Priority | Type | Title | Steps | Expected Result |
|----|----------|------|-------|-------|-----------------|
| EDGE-N01 | P1 | A | Ingest from unknown minion ID | POST grains with unregistered minion_id | HTTP 401 (token check fails — no node record with that ID) |
| EDGE-N02 | P1 | A | Ingest with wrong token | POST grains with valid minion_id but wrong token | HTTP 401 |
| EDGE-N03 | P1 | A | Ingest with revoked token | Bootstrap node (generates token), then bootstrap again (rotates token), use old token | HTTP 401 |
| EDGE-N04 | P2 | A | Grain ingest with missing fqdn | POST grains without `fqdn` key | hostname tag not created; other tags still populated from available grains |
| EDGE-N05 | P2 | A | Grain ingest with empty serialnumber | POST grains with `serialnumber=""` | serial tag not created (empty value skipped) |
| EDGE-N06 | P2 | A | Concurrent grain ingests from same node | Two POST requests simultaneously | Both succeed; last-write-wins for node fields; no duplicate tags created |
| EDGE-N07 | P1 | M | Add tag with empty key | Tag form: leave key blank, enter value, submit | Browser validation prevents submit (required field) |
| EDGE-N08 | P1 | M | Add tag with empty value | Tag form: enter key, leave value blank, submit | Browser validation prevents submit |
| EDGE-N09 | P2 | A | Add tag exceeding key length limit | POST tag with 101-char key | HTTP 422 validation error |
| EDGE-N10 | P2 | A | Node with no IP address | Create node via bootstrap with empty IP somehow | bootstrap_ip null; group playbook targeting this node logs "No hosts with IP addresses" |

---

### 15.3 Group Edge Cases

| ID | Priority | Type | Title | Steps | Expected Result |
|----|----------|------|-------|-------|-----------------|
| EDGE-G01 | P1 | M | Add node already in group | In Group Detail, attempt to add node that's already a member | Node not in dropdown (filtered out); if forced via API: idempotent or error |
| EDGE-G02 | P1 | A | Add node to dynamic group | POST `/api/v1/groups/{dynamic_id}/members` | HTTP 400 or 409 "dynamic group members are resolved automatically" |
| EDGE-G03 | P1 | M | View dynamic group | Open a dynamic group | No "+ Add node" button, no Remove column; predicate shown |
| EDGE-G04 | P2 | A | Group with 0 members targeted by playbook | Run playbook with target_type=group, group has 0 members | Job fails with "No hosts with IP addresses found" |
| EDGE-G05 | P2 | A | Group where all members have no IP | Run playbook targeting group where no node has ip_address | Job fails with "No hosts with IP addresses found for the selected target" |
| EDGE-G06 | P2 | M | Delete node that is in multiple groups | Remove a node from fleet | Node removed from all group member tables |
| EDGE-G07 | P1 | M | Create group with duplicate name | Create two groups with same name | Second creation may succeed (name not unique-constrained) or error — verify API behaviour |

---

### 15.4 Baseline Edge Cases

| ID | Priority | Type | Title | Steps | Expected Result |
|----|----------|------|-------|-------|-----------------|
| EDGE-BL01 | P1 | M | Create baseline with empty JSON `{}` | Enter `{}` as state_json | Valid JSON, Create succeeds; baseline created with empty state (zero drift always) |
| EDGE-BL02 | P1 | M | Create baseline with invalid JSON | Enter `{broken` in JSON editor | Red border, error message, Create disabled |
| EDGE-BL03 | P1 | M | Create baseline without name | Leave name blank, click Create | Create button disabled (required field) |
| EDGE-BL04 | P2 | M | Create group baseline with no group selected | Select target=Group, leave dropdown empty | Create button disabled |
| EDGE-BL05 | P2 | A | Create baseline with non-existent target_id | POST with `target_type=node, target_id=00000000-...` | HTTP 404 or baseline created referencing ghost node (depends on FK constraints) |
| EDGE-BL06 | P2 | A | Very large state_json | POST with thousands of packages in state_json | Should succeed (JSONB has no practical size limit in PostgreSQL) |

---

### 15.5 Playbook Edge Cases

| ID | Priority | Type | Title | Steps | Expected Result |
|----|----------|------|-------|-------|-----------------|
| EDGE-P01 | P1 | A | Run playbook targeting node with no IP | POST run with node_id that has no ip_address | Job created but immediately fails with "No hosts with IP addresses" |
| EDGE-P02 | P1 | A | Run unknown playbook | POST with `playbook="doesnt_exist.yml"` | HTTP 404 "Playbook not found" |
| EDGE-P03 | P1 | A | Path traversal in playbook filename | POST with `playbook="../../etc/hosts"` | HTTP 404 (not in discover_all allowlist) |
| EDGE-P04 | P2 | M | Playbook file deleted after discovery | Discover playbooks, then delete `bootstrap_mac_mini.yml`, try to run | Job fails at task level; status=failed, stdout shows file not found |
| EDGE-P05 | P2 | A | Run playbook with empty extravars | POST run with `extravars: {}` | Job succeeds; no host_vars/group_vars file written |
| EDGE-P06 | P2 | A | extravars value with path traversal | POST run with `extravars: { "key": "../../etc/evil" }` | Value written safely to YAML (yaml.dump escapes it); no filesystem traversal |
| EDGE-P07 | P2 | M | Run playbook while another is running on same node | Submit two playbook runs for same node | Both jobs created; Celery runs them sequentially (queue is ordered) |
| EDGE-P08 | P2 | A | Get status of non-existent job | `GET /api/v1/ansible/jobs/00000000-...` | HTTP 404 |
| EDGE-P09 | P1 | A | Playbook content for non-existent file | `GET /api/v1/ansible/playbooks/content?filename=ghost.yml` | HTTP 404 |

---

### 15.6 Settings Edge Cases

| ID | Priority | Type | Title | Steps | Expected Result |
|----|----------|------|-------|-------|-----------------|
| EDGE-S01 | P1 | M | Save settings with all fields blank | Open Settings, clear all fields, click Save | Sends `undefined` for all fields; no settings overwritten (blank = "keep existing") |
| EDGE-S02 | P1 | A | PUT settings with only one field | PUT `{ "salt_master_address": "10.0.0.2" }` | Only `salt_master_address` updated; all other settings unchanged |
| EDGE-S03 | P2 | M | Very long salt master address | Enter 200-char address, save | API accepts or returns 422 (string length validation) |
| EDGE-S04 | P2 | A | GET settings as non-admin | GET `/api/v1/settings` as viewer | HTTP 403 |
| EDGE-S05 | P2 | M | Settings page load when platform_settings table empty | First boot with no settings rows | All fields show empty/placeholder; controller key shows "No keypair generated yet" warning |
| EDGE-S06 | P1 | M | SSH password cleared after save | Enter password, save, reload Settings page | Password field is empty (never shown after save) |

---

### 15.7 Authentication & Session Edge Cases

| ID | Priority | Type | Title | Steps | Expected Result |
|----|----------|------|-------|-------|-----------------|
| EDGE-A01 | P1 | M | Access protected page when logged out | Navigate to `/fleet` directly without logging in | Redirected to `/login` |
| EDGE-A02 | P1 | M | Token expires during session | Stay logged in past token expiry (default ~30min) | Next API call fails with 401; auto-redirect to login |
| EDGE-A03 | P2 | M | Multiple tabs — logout from one | Log in on two tabs, logout on Tab A | Tab B eventually gets 401 on next API call and redirects |
| EDGE-A04 | P2 | A | Use refresh token twice | Call `/auth/refresh` with the same refresh token twice | Second call returns 401 (token revoked after first use) |
| EDGE-A05 | P2 | A | Login with inactive user | If user marked inactive in DB | HTTP 401 or 403 |
| EDGE-A06 | P1 | A | Rate limit login endpoint | > 60 login attempts per minute | HTTP 429 |

---

### 15.8 Infrastructure & Reliability Edge Cases

| ID | Priority | Type | Title | Steps | Expected Result |
|----|----------|------|-------|-------|-----------------|
| EDGE-I01 | P1 | A | API starts with Redis down | Stop Redis, restart API | `/health/ready` returns `{ status: "degraded", checks: { redis: "error" } }`, HTTP 503 |
| EDGE-I02 | P1 | A | API starts with DB down | Stop PostgreSQL, restart API | `/health/ready` returns degraded, HTTP 503 |
| EDGE-I03 | P2 | A | Large SBOM payload rejected | POST SBOM > 50 MB to ingest endpoint | HTTP 413 "SBOM payload too large" |
| EDGE-I04 | P2 | A | Ingest rate limit hit | > 60 grain ingests per minute from same IP | HTTP 429 |
| EDGE-I05 | P2 | M | Celery worker restart mid-task | Kill Celery worker while bootstrap is running | Job may stay in "bootstrapping" state indefinitely; operator must cancel manually |
| EDGE-I06 | P2 | A | Git repo in detached HEAD | Put git repo in detached HEAD, run playbook with extravars | `_commit_var_files` logs a warning (non-fatal); var file written to disk but not committed; playbook still runs |
| EDGE-I07 | P3 | M | 500+ nodes in fleet | Simulate or seed 500 nodes | Fleet Dashboard paginates correctly, per-page selector works, no timeout on overview endpoint |
| EDGE-I08 | P3 | A | Concurrent drift computes for same node | Send 10 simultaneous POST `/drift/{id}/compute` | All return `{ status: "queued" }`; Celery deduplicates or runs them sequentially |
| EDGE-I09 | P2 | A | Migration on DB with existing data | Run `alembic upgrade head` on DB that already has data | Migration completes without data loss; existing rows get default values for new columns |

---

### 15.9 Search Edge Cases

| ID | Priority | Type | Title | Steps | Expected Result |
|----|----------|------|-------|-------|-----------------|
| EDGE-SR01 | P1 | M | Search with exactly 2 chars | Type 2 chars in TopBar search | Dropdown stays closed (enabled at 3 chars) |
| EDGE-SR02 | P1 | M | Search with exactly 3 chars | Type 3rd char | Dropdown opens, search fires |
| EDGE-SR03 | P2 | M | Search with special characters | Type `mac-mini-01` (with dashes) | Returns correct match |
| EDGE-SR04 | P2 | A | Search with SQL injection pattern | `GET /api/v1/search?q=' OR '1'='1` | Returns empty results or normal match — not a SQL error |
| EDGE-SR05 | P2 | A | Search with very long query | 500-char search string | Returns 422 or empty results (not a 500 error) |
| EDGE-SR06 | P3 | M | Rapid typing debounce | Type quickly, character by character | Only one search fires (debounced), not one per character |

---

### 15.10 UI / UX Edge Cases

| ID | Priority | Type | Title | Steps | Expected Result |
|----|----------|------|-------|-------|-----------------|
| EDGE-UX01 | P2 | M | Playbook variable editor — all fields are system vars | Playbook only has ansible_* vars | All inputs shown in amber, each labelled "⚠ system var" |
| EDGE-UX02 | P2 | M | Bootstrap modal — minion ID cleared, IP clears too | Type minion ID (gets auto-filled IP), then clear minion ID | IP field clears and becomes editable again |
| EDGE-UX03 | P2 | M | Bootstrap modal — same minion ID re-typed | Type minion ID, clear it, retype same value | Node lookup fires again, IP re-populates |
| EDGE-UX04 | P1 | M | Playbook JSON editor — paste invalid JSON | Paste malformed JSON into baseline creator | Immediate inline error message, Create disabled |
| EDGE-UX05 | P2 | M | Groups dropdown in Group Detail — all nodes already members | Static group has all fleet nodes as members | "+ Add node" dropdown shows no options (all filtered out) |
| EDGE-UX06 | P2 | M | Fleet Dashboard — filter + pagination interaction | Filter by "online", navigate to page 2, then change filter to "All" | Page resets to 1 with new filter results |
| EDGE-UX07 | P3 | M | Very long hostname | Node with 255-char hostname | Hostname truncated in table but shown fully in node detail |
| EDGE-UX08 | P2 | M | Modal scrolling — long variable list | Playbook with 20+ variables | Variables panel scrolls independently; Run button stays pinned at bottom |
| EDGE-UX09 | P2 | M | Bootstrap stuck warning — refresh page | Node in bootstrapping state; navigate away and back | Node Detail still shows Bootstrap Status card with "Running…" and Cancel button |
| EDGE-UX10 | P3 | M | Sidebar tooltip on last item | Hover "Settings ⚙" icon in collapsed sidebar | Tooltip appears; does not clip off-screen |

---

## Test Accounts

| Email | Password | Role |
|-------|----------|------|
| `admin@fleet.local` | `changeme123` | admin |
| `admin@admin.com` | `admin` | admin |

---

## Quick Reference — Test Data

```bash
# Seed a test node directly in DB (for testing without a real Mac Mini)
docker exec deploy-postgres-1 psql -U fleet -d fleet_demo -c "
INSERT INTO nodes (id, minion_id, hostname, ip_address, status, drift_score,
  node_token_hash, first_seen_at, bootstrap_status)
VALUES (
  gen_random_uuid(), 'test-mini-01', 'test-mini-01', '10.0.1.99',
  'online', 0, 'placeholder_hash', now(), 'completed'
) ON CONFLICT DO NOTHING;"

# Reset a stuck bootstrap node
docker exec deploy-postgres-1 psql -U fleet -d fleet_demo -c "
UPDATE nodes SET bootstrap_status='failed', bootstrap_error='Manually reset for testing'
WHERE minion_id='test-mini-01';"

# Create a test tag directly
docker exec deploy-postgres-1 psql -U fleet -d fleet_demo -c "
INSERT INTO tags (id, node_id, key, value, source, created_at)
SELECT gen_random_uuid(), id, 'test-key', 'test-value', 'user', now()
FROM nodes WHERE minion_id='test-mini-01'
ON CONFLICT DO NOTHING;"
```

---

*Total test cases: 230+ (120 feature tests + 75 edge cases + 35 user journey steps)*
