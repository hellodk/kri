# Fleet correctness plan: topology, grains, bootstrap (+ agentic epic pointer)

Status: WS1 implemented (code + playbook, unit tests green); WS2/WS3 pending.
GitHub: epic #706, WS1 #707, WS2 #708, WS3 #709.
Scope: three operational workstreams (WS1–WS3) shipped as one PR, plus a
pointer to the separate agentic-transformation epic (WS4).

---

## WS1 — Topology correctness ("no nodes assigned to master mm")

### Problem
`node.salt_master_id` is only ever set by:
- the one-time backfill in migration `041_salt_masters.py` (every NULL → "first master"), and
- reassign-on-delete in `api/routes/salt_masters.py` (deleted master's nodes → default).

Nothing derives the link from the master that actually reports a minion.
`workers/salt_presence_tasks.py::sync_minion_presence` calls `manage.up`
per-master but **unions** the results into a set and never records ownership.
Because `cylon` was created first, every node was pinned to it; the `mm`
minion therefore never appeared under the `mm` master.

Additionally, `playbooks/install_salt_master.yml` installs the **master only**
— it does not co-locate a `salt-minion` on the master, so a master is not a
managed node of itself.

### Fix
1. `workers/salt_presence_tasks.py`
   - Add `id` to each entry in `master_conns`.
   - Track `minion_id -> reporting master ids` instead of a flat union.
   - When marking a node online, set `node.salt_master_id` to a reporting
     master when the node is unassigned OR its current master did **not**
     report it this cycle (prefer the default master when multiple report it).
   - Keep "online if up on ANY master" semantics (#689).
2. `playbooks/install_salt_master.yml` / `roles/salt_master`
   - Opt-in `salt_master_install_minion: true` (default on): install
     `salt-minion` on the master, point it at `127.0.0.1`, auto-accept its own
     key, and register/self-assign the node.

### Acceptance
- After one presence cycle, every online node's `salt_master_id` matches the
  master that reports it.
- `mm` master page lists its own minion.
- Unit test covers the reassignment logic (reported-by master wins over a
  stale assignment).

---

## WS2 — Grain collection via salt-api (remove container SSH key dependency)

### Problem
`workers/ansible_tasks.py::collect_node_grains` SSHes from the worker
container into the node using `~/.kri/id_rsa` and runs `salt-call --local
grains.items`. The worker runs as `uid 1001 (appuser)` but the key is `0600`
owned by host `uid 1000`, so it fails with `[Errno 13] Permission denied:
'/home/appuser/.kri/id_rsa'` and never attempts SSH. The master already
manages the minion, so SSH + a container-side key is the wrong mechanism.

### Fix
1. Rewrite `collect_node_grains` to call **salt-api `grains.items`** via the
   local client, targeting `minion_id`, using the node's master API creds.
   No SSH, no container key. (Verify `grains.items` is whitelisted for the
   `krisalt` external_auth user in `kri-master.conf`.)
2. Keep SSH `salt-call --local` only as a fallback for not-yet-connected
   nodes.
3. `frontend/src/pages/NodeDetail.tsx`: replace the hardcoded
   "Grain collection requires SSH access … Offline nodes cannot be reached."
   message with the actual `reason` from the task.

### Acceptance
- Grains collected for an online minion with no container-side key present.
- The UI shows the real failure reason when collection fails.

---

## WS3 — OS-aware bootstrap + node_exporter (Item 3)

### Scope decision
Bootstrap has **one responsibility**: turn a host into a managed **salt-minion**
plus **node_exporter**. It never installs master components. Promoting a node
to a salt-master is a separate, console-driven action (`provision_master` /
"promote topology" #560, backed by `install_salt_master.yml`) — and that
master-install path is where the co-located minion (WS1) lives.

### Problem
`workers/ansible_tasks.py::bootstrap_node` hardcodes the macOS-only
`bootstrap_mac_mini.yml`. Linux minion bootstrap is unsupported. Error
classification checks `UNREACHABLE` before auth-failure strings, so SSH auth
failures are mislabeled "SSH unreachable".

### Fix (single playbook, conditionals — no separate Linux playbook)
1. Generalize the bootstrap playbook with `when: ansible_os_family == 'Darwin'`
   vs Linux branches — **minion install only**:
   - Darwin: Homebrew/onedir + launchd (existing path).
   - Linux: salt-bootstrap (or apt/yum) + systemd unit.
2. Route `bootstrap_node` to the unified playbook (drop the mac-only hardcode).
3. Add **node_exporter** install + service to the same flow:
   - macOS: launchd plist.
   - Linux: systemd unit.
4. `workers/ansible_tasks.py`: check auth-failure strings **before**
   `UNREACHABLE` in error classification.
5. No master logic in bootstrap (see scope decision above).

### Acceptance
- `.13` / `.14` bootstrap successfully as minions.
- node_exporter running and scrapeable on bootstrapped nodes.
- macOS bootstrap path unchanged (regression-safe).
- Bootstrap installs no salt-master/salt-api components.

---

## WS4 — Agentic transformation epic (separate)

Source: `kri-chat.txt` (principal-engineer audit + 6-phase roadmap A–F) to turn
kri's LLM surface into a real agentic system: typed JSON-Schema tool registry,
tool executor + agent loop, quarantine write surface
(`/srv/kri/agent-quarantine/`), PendingAction-gated apply-with-approval, local
MLX cluster on the 18 minis (planner/coder/worker tiers), and security
hardening. Estimated ~8 weeks (4–5 weeks with two engineers).

This is tracked as a GitHub **epic** with one issue per phase (A–F). It is NOT
part of the WS1–WS3 infra PR. Item 3's node_exporter work is the manual
precursor to the doc's Scenario B (agent-generated node_exporter playbook).
