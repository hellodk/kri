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

## Test Accounts

| Email | Password | Role |
|-------|----------|------|
| `admin@fleet.local` | `changeme123` | admin |
| `admin@admin.com` | `admin` | admin |

---

*Total test cases: 120+*
