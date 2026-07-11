# 2026-07-05 — Add 3 nodes + make .64 the salt master

Running log of issues hit while enrolling three hosts into kri and switching the
salt master to `192.168.1.64`. Work branch: `fix/add-nodes-bootstrap`.

## Target topology

| Host | IP | OS / arch | Role |
|------|----|-----------|------|
| mm | `192.168.1.64` (Tailscale `100.102.68.75`) | macOS 15, arm64 | **salt master** (control plane) + minion of itself |
| cylon (= this box, "bodhi") | `192.168.1.10` (Tailscale `100.89.50.27`) | Ubuntu 24.04, x86_64 | kri control plane host + salt minion |
| Abhisheks-Mac-mini | `192.168.1.5` | macOS 15, arm64 | salt minion |

Extra pre-existing failed node: `192.168.1.23` (leave as-is unless asked).

## Environment facts (verified)
- All three reachable over SSH from cylon as user `dk` with passwordless sudo (key auth).
- `192.168.1.64` == `mm1` (`100.102.68.75`) — the historical salt master. salt 3007.14 + master PKI already installed there, but the **salt-master/salt-api services were stopped** (only `com.saltstack.salt.minion` loaded; ports 4505/4506/4507 closed).
- The kri platform (this task's "bodhi") actually runs on **cylon** (`192.168.1.10` / `100.89.50.27`) via Docker Compose.

## Root-cause findings (static analysis)

### Issue A — only a bogus `e2e-master` salt master registered
`salt_masters` table had one row: `e2e-master`, address `127.0.0.1`, status `unreachable`,
`is_default=true`. The bootstrap worker writes the minion config `master:` list from the
**enabled** salt master addresses, so every prior bootstrap pointed minions at `127.0.0.1`.
- Fix: register `192.168.1.64` as the enabled default master; disable/remove `e2e-master`.

### Issue B — master config `auto_accept: False` + post-bootstrap key accept ⇒ deadlock/hang
`playbooks/roles/salt_master/templates/kri-master.conf.j2` sets `auto_accept: False`.
The worker (`ansible_tasks.bootstrap_node`) only accepts the minion key **after** the
playbook returns (step 6a `run_wheel key.accept`). But `bootstrap_node.yml`'s
"Apply kri heartbeat schedule via salt-call" runs `salt-call state.apply base.heartbeat`
(a master-contacting call) **during** the playbook. With the key unaccepted and
`master_tries: -1`, that call blocks until the 10-min ansible-runner timeout →
`bootstrap_status=failed` "Timed out … Last task: Apply kri heartbeat schedule via salt-call".
This matches the observed `.64` / `.5` failures.
- Candidate fixes (prefer Salt/Ansible config): enable `auto_accept` on the master
  (matches the kri `SaltMaster.auto_accept=True` model default + trusted-LAN policy),
  and/or make the in-playbook `salt-call state.apply` steps fail fast (timeout) so
  bootstrap completes and the post-run key-accept + server-side grain pull take over.

### Issue C — one-time bootstrap grain push targets the master, not the kri API
`ingest_url = http://{first_master_address}/api/v1/ingest` in the worker. With the master
on `.64` (a Mac not running kri) the on-node grain push in `bootstrap_node.yml` cannot reach
kri. Non-fatal (`failed_when: false`), and "online" status is maintained server-side by the
`refresh_all_node_grains` → `collect_node_grains` beat task (pulls grains over salt-api,
posts to internal `http://api:8000`). Noted; revisit only if nodes don't go online.

## Actions & outcomes
(updated as work proceeds)
