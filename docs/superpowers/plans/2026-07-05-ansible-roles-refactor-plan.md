# Ansible Playbooks → Roles Refactor + Efficiency Review — Plan

- **Date:** 2026-07-05
- **Scope:** `playbooks/` only (bootstrap, salt-minion, salt-master, node_exporter, node telemetry deps, kri redeploy). No production code changes in this document — this is a written plan.
- **Status:** Plan — pending user review. **Nothing here has been implemented.**
- **Related prior design:** `docs/superpowers/specs/2026-06-26-ansible-role-consolidation-design.md` (role consolidation + push telemetry). This plan is the *roles-refactor + efficiency* execution view of that spec, adds a concrete line-by-line efficiency audit, and stays strictly inside the "reorganize into roles" ask. Push-telemetry (`otel_agent`, `hw_exporter`) is referenced as forward-alignment but is **not** the focus.

---

## 0. How the deliverable was produced (expert consultation)

The role structure and lint findings below are grounded in current (2026) authoritative Ansible guidance, pulled live:

- **Role directory structure** — official Ansible docs, "Roles": the standard layout is `roles/<role>/{tasks,handlers,templates,files,vars,defaults,meta,library}/main.yml`; include only the dirs you use; roles are found relative to the playbook, in `roles/`, or in a configured `roles_path`. Source: <https://docs.ansible.com/projects/ansible/latest/playbook_guide/playbooks_reuse_roles.html>
- **`ansible-lint` production profile** — the strictest profile (AAP certified-content bar). Rules relevant here: `fqcn` (fully-qualified module names), `use-loop`, `no-changed-when`, `command-instead-of-module`, `command-instead-of-shell`, `risky-shell-pipe`, `no-free-form`, `partial-become`, `name[missing]`, `var-naming`, `meta-no-dependencies`, `deprecated-local-action`, `package-latest`. Sources: <https://docs.ansible.com/projects/lint/profiles/> and <https://docs.ansible.com/projects/lint/rules/fqcn/>
- **Idempotency with shell/command** — always prefer a module; when shell is unavoidable, add `register` + `changed_when` (and `creates`/`removes` where possible), and use `changed_when: false` for read-only probes. Source: <https://docs.ansible.com/projects/ansible/latest/playbook_guide/playbooks_reuse_roles.html> plus lint `no-changed-when` rule and community guidance <https://ciq.com/blog/achieving-idempotency-with-shell-commands>.

All three tools (WebSearch/WebFetch, repo read, graph orientation) were available; findings are cited inline.

---

## 1. Invocation constraints (must not break these)

Read from `fleet_platform/workers/playbook_tasks.py` and `fleet_platform/services/playbook_discovery.py`:

1. **Playbooks are addressed by filename.** `run_playbook` stores `job.playbook` (e.g. `bootstrap_node.yml`, `deploy_node_exporter.yml`, `roles/salt_minion`) and resolves it via `_resolve_playbook_path`. **Renaming or deleting a playbook filename breaks any saved job, scheduled run, or Playbook-Library entry that references the old name.** Consolidation must keep the old filenames as thin shims (or coordinate a DB/library migration) — see Phase notes.
2. **Inventory group is `[targets]`** (`_write_static_inventory`), with `[all:children] → targets`. Plays must target `hosts: targets` or `hosts: all`. `install_salt_master.yml` uses `hosts: "{{ target_host }}"` and `deploy_salt_master_mm1.yml` uses `hosts: all` — both work today but are inconsistent; the consolidated master playbook should standardize on `hosts: all` (worker-friendly) with a documented manual-run path.
3. **Roles are found via `ANSIBLE_ROLES_PATH = <playbooks_dir>/roles`** (set per-run by the worker) — so **all roles must live under `playbooks/roles/`**. Do not move roles elsewhere.
4. **A role can be run directly.** If `job.playbook` is a directory (e.g. `roles/salt_minion`), the worker synthesizes a wrapper play `hosts: targets / gather_facts: true / roles: [<name>]`. So every role must be safe to run standalone with facts gathered by that wrapper (no reliance on a `pre_tasks` block that only exists in `bootstrap_node.yml`).
5. **`ANSIBLE_CONFIG` is always `playbooks/ansible.cfg`**; **collections come from `playbooks/collections/installed`**. New module usage (e.g. `community.general.homebrew`) requires that collection to be vendored there, or the `#357` pre-flight will fail the run. `ansible.posix` is already vendored; `community.general` presence must be verified before adopting its modules.
6. **Extravars only** — secrets/vars are passed via `run_async(extravars=...)`, never persisted. Role `defaults/` must be overridable by extravars (they are — defaults are lowest precedence).
7. **Discovery reads `defaults/main.yml`** for a role's default vars + the `_kri_var_descriptions` meta-key to build the run-modal form. New roles should include `defaults/main.yml` with `_kri_var_descriptions` to render nicely in the kri Automation Hub.

---

## 2. Inventory of current Ansible content

Ansible lives under `playbooks/` (`ansible.cfg`, `inventory/hosts.ini`, `group_vars/all.yml`, `host_vars/mm1.yml`, top-level playbooks, `tasks/bootstrap/`, and two existing roles). The vendored `playbooks/collections/installed/…` tree is upstream collection code — **out of scope**.

### 2.1 Playbooks (file → purpose → issues)

| File | Purpose | Key issues found |
|---|---|---|
| `bootstrap_node.yml` (534 lines) | Monolith: arch/OS detect, master reachability gate, Xcode CLT, salt-minion install (macOS inline + Linux include), minion config, service start, authorized_keys, VNC, macOS grains collection, node_deps include, salt schedules, grains push (×2), node_exporter include (×2) | ~10 concerns in one play; salt-minion install duplicated vs `salt_master` role; OS split via includes not conditionals inside a role; duplicated grains-push `uri` blocks (L452/L490); shell used where facts/modules exist (L347–408 duplicate gathered facts); `ps aux \| grep` (L311); no tags, no handlers, no block/rescue; per-task `become`. |
| `install_salt_master.yml` | Install salt-master on a **macOS** Mac Mini (air-gapped `.pkg`) + legacy pillar export | Near-duplicate of the other 3 master playbooks; `hosts: "{{ target_host }}"` targeting differs from worker `[targets]`; two localhost `pre`/export plays inline. |
| `install_salt_master_linux.yml` | Same, **Linux** target (apt/yum) | Duplicate wrapper; only differs from the macOS one by `gather_facts`/notes; the `salt_master` role already handles OS internally, so the split is unnecessary. |
| `setup_salt_master.yml` | Install salt-master on mm1 + export pillar from old Docker container | Duplicate wrapper; localhost pillar-export logic overlaps `install_salt_master.yml`. |
| `deploy_salt_master_mm1.yml` | Install salt-master (native) via `hosts: all` | Duplicate wrapper; hardcodes `kri_salt_api_password: "changeme-set-via-e-flag"` default (L22) — risky default password. |
| `deploy_node_exporter.yml` | Apply `node_exporter` role to `targets` | Thin + correct shape, but points at the **weak/drifted** `node_exporter` role (see 2.3). |
| `redeploy_kri.yml` | git pull + `docker compose up -d --build` + health check on kri host | `command: git pull` / `docker compose` / `cat VERSION` have no `changed_when` (always report changed); `cat` should be `slurp`/`ansible.builtin.command` with `changed_when: false`. |

### 2.2 Shared task files (candidates to fold into roles)

| File | Purpose | Fate |
|---|---|---|
| `tasks/bootstrap/minion_linux.yml` | apt/yum repo + install `salt-minion` | → **`salt_minion` role** (`install_debian.yml`/`install_redhat.yml`). Duplicates `salt_master/tasks/install_debian.yml`. |
| `tasks/bootstrap/node_deps.yml` | psutil (both OS), macmon+tart (macOS brew) | → **`node_telemetry` role**. Repeated check/install pairs; `shell` brew instead of `community.general.homebrew`; pip via shell instead of `ansible.builtin.pip`. |
| `tasks/bootstrap/node_exporter_linux.yml` | node_exporter via systemd (arch-aware, checksum-less, version-gated) | → **canonical `node_exporter` role** (Linux path). Strong impl; merge target. |
| `tasks/bootstrap/node_exporter_macos.yml` | node_exporter via launchd | → **canonical `node_exporter` role** (macOS path). |

### 2.3 Existing roles

| Role | State | Issues |
|---|---|---|
| `roles/salt_master/` | Mature, mostly good, fully split into task files (`install_*`, `configure`, `pki`, `pillar`, `states`, `api_user`, `api_tls`, `service_*`, `verify`, `minion`); has README, defaults, handlers, templates | **`service_systemd.yml`/`service_macos.yml` force `state: restarted` on every run** → not idempotent (contradicts README's "no-op re-apply"); handlers exist but are bypassed by these forced restarts; bare (non-FQCN) module names throughout; `local_action` (deprecated form) in `install_macos.yml`; `install_macos.yml` hardcodes `arm64` pkg (L13) despite computing `cpu_arch`; checksum verified via `shell`+`shasum` instead of `get_url checksum:`; `validate_certs: false` on Artifactory download; `api_user.yml` macOS branch uses non-deterministic `RANDOM` UID; **no `meta/main.yml`**. |
| `roles/node_exporter/` | **Weak, drifted duplicate** of the `tasks/bootstrap/node_exporter_*.yml` implementation | `meta: end_play` (linux.yml L9, macos.yml L9) **ends the whole play for all hosts**, not just the current host — a real bug in multi-host runs; hardcoded arch (`linux-amd64`, `darwin-arm64`); no checksum; GitHub-only URL (no Artifactory/air-gap); runs node_exporter as **root** (no dedicated user on the mac path, and linux path here lacks the user the bootstrap-task version creates); different variable scheme (`node_exporter_port`/`node_exporter_install_dir`) than the bootstrap tasks (`node_exporter_listen_address`); `ignore_errors: true`; handler only for macOS. **This is the primary drift to eliminate.** |

### 2.4 Support files

- `ansible.cfg` — sane worker-oriented defaults (`forks=20`, `pipelining=True`, `host_key_checking=False`, `task_timeout=300`). `deprecation_warnings=False` hides useful migration signals; no `roles_path` set (worker supplies it via env — fine).
- `inventory/hosts.ini` — static groups (`salt_master`, `fleet`, `kri_host`, `targets`). Worker generates its own inventory at runtime; this file is for manual runs.
- `group_vars/all.yml` — well-documented shared vars (salt version, URLs, brew prefixes, node_exporter version, Artifactory layout). Good; will become the shared defaults surface.
- `host_vars/mm1.yml` — per-host become/ssh vars.

---

## 3. Target role catalog

Rule applied (from the prior spec, kept): **a role is a reusable, cohesive installer; bootstrap-only orchestration glue stays in the playbook.**

| Role | Responsibility | Content moved in | Key defaults/vars | Handlers | Templates/files |
|---|---|---|---|---|---|
| **`common`** (new, tiny) | Normalize OS/arch facts once so every role/play shares them | arch detect (`cpu_arch`, `ne_arch`), `ne_os`, `brew_prefix`, `salt_group`, macOS `brew_user` detection (from `bootstrap_node.yml` L31–105) | `brew_prefix_arm64/x86` | — | — |
| **`salt_minion`** (new) | Install + configure + start the Salt minion (macOS `.pkg` / Debian apt / RedHat dnf), pre-seed master pubkey, HA failover config | macOS install block (`bootstrap_node.yml` L130–222), `tasks/bootstrap/minion_linux.yml`, minion config write (L230–286), service start (L288–317) | `salt_version`, `salt_masters` (list, required), `minion_id`, `salt_master_pub_key?`, `salt_pkg_*` URL tiers | `Restart salt-minion` (launchd/systemd) | `minion.conf.j2` (replaces inline `copy: content:`) |
| **`salt_master`** (keep + refactor) | Install salt-master + salt-api (api as a tagged sub-step), PKI, pillar, states, TLS, service, verify, co-located minion | existing role — fix idempotency + FQCN + meta (no content moves) | existing defaults (good) | existing (make them the *only* restart path) | existing `.j2` templates |
| **`node_exporter`** (merge → canonical) | Prometheus node_exporter, arch-aware, checksum, dedicated system user, systemd/launchd; **optional, off by default in bootstrap** | canonical body from `tasks/bootstrap/node_exporter_{linux,macos}.yml`; **delete** the weak `roles/node_exporter` body | unify on `node_exporter_version`, `node_exporter_listen_address` (map legacy `node_exporter_port`/`install_dir`), URL override tiers | `Restart node_exporter` (systemd + launchd) | `node_exporter.service.j2`, `io.prometheus.node_exporter.plist.j2` |
| **`node_telemetry`** (new) | psutil (both OS), macmon + tart (macOS) via a single loop | `tasks/bootstrap/node_deps.yml` | package lists per OS, `monitoring_interval` | — | — |
| **`kri_enroll`** (new, optional) | Push initial grains to kri ingest API + apply salt heartbeat/process schedules (reusable "re-enroll") | grains push ×2 (`bootstrap_node.yml` L452–524, deduped into one OS-conditional task) + salt-call schedules (L421–449) | `ingest_url`, `node_token`, `minion_id` | — | — |

**Bootstrap-only glue that stays inline** in `bootstrap_node.yml` (as `pre_tasks`/`tasks`, optionally factored to `tasks/host_prep.yml`): master-reachability gate (L61–91), Xcode CLT (L108–128), authorized_keys (L319–334), VNC enable (L336–344), macOS grains *collection* commands feeding `kri_enroll`.

**Forward-alignment (from the 2026-06-26 spec, not built here):** `otel_agent` and `hw_exporter` roles for push telemetry. The directory tree below leaves room for them.

### 3.1 Playbooks become thin orchestrators

```yaml
# bootstrap_node.yml (target shape)
- hosts: targets
  gather_facts: false
  pre_tasks:
    - import_role: { name: common }            # arch/OS facts
    - import_tasks: tasks/host_prep_gate.yml    # master reachability, fail-fast
  roles:
    - salt_minion                               # always
    - node_telemetry                            # always
    - { role: node_exporter, when: node_exporter_enabled | default(false) }
    - kri_enroll                                # grains push + salt schedules
  tasks:
    - import_tasks: tasks/host_prep.yml          # Xcode CLT, authorized_keys, VNC
```

```yaml
# install_salt_master.yml (ONE playbook replaces 4)
- hosts: all
  gather_facts: true
  roles:
    - salt_master        # OS handled inside the role; salt-api via --tags api
```

`deploy_node_exporter.yml` keeps its filename and its `roles: [node_exporter]` shape (now pointing at the canonical role).

---

## 4. Target directory tree (before → after)

**Before:**
```
playbooks/
  ansible.cfg  inventory/hosts.ini  group_vars/all.yml  host_vars/mm1.yml
  bootstrap_node.yml
  install_salt_master.yml
  install_salt_master_linux.yml
  setup_salt_master.yml
  deploy_salt_master_mm1.yml
  deploy_node_exporter.yml
  redeploy_kri.yml
  tasks/bootstrap/{minion_linux,node_deps,node_exporter_linux,node_exporter_macos}.yml
  roles/
    salt_master/{tasks/*,handlers,defaults,templates,README.md}
    node_exporter/{tasks/{main,linux,macos},handlers,defaults}   # weak/drifted
  files/  collections/installed/…(vendored)
```

**After:**
```
playbooks/
  ansible.cfg  requirements.yml            # NEW: pin ansible.posix + community.general
  inventory/hosts.ini  group_vars/all.yml  host_vars/mm1.yml
  bootstrap_node.yml                        # thin orchestrator
  install_salt_master.yml                   # ONE master playbook (OS-conditional role)
  install_salt_master_linux.yml             # SHIM → import_playbook: install_salt_master.yml (back-compat)
  setup_salt_master.yml                     # SHIM (back-compat) or removed w/ library migration
  deploy_salt_master_mm1.yml                # SHIM (back-compat)
  deploy_node_exporter.yml                  # unchanged filename → canonical role
  redeploy_kri.yml                          # idempotency fixes only
  tasks/
    host_prep_gate.yml                      # master reachability fail-fast (was inline)
    host_prep.yml                           # Xcode CLT, authorized_keys, VNC (was inline)
  roles/
    common/          tasks/main.yml  defaults/main.yml  meta/main.yml
    salt_minion/     tasks/{main,install_macos,install_debian,install_redhat,configure,service}.yml
                     handlers/main.yml  defaults/main.yml  templates/minion.conf.j2  meta/{main,argument_specs}.yml
    salt_master/     (existing, + meta/main.yml, + argument_specs, idempotency fixes)
    node_exporter/   tasks/{main,install,service_systemd,service_launchd}.yml
                     handlers/main.yml  defaults/main.yml  templates/{node_exporter.service.j2,plist.j2}  meta/main.yml
    node_telemetry/  tasks/{main,macos,linux}.yml  defaults/main.yml  meta/main.yml
    kri_enroll/      tasks/main.yml  defaults/main.yml  meta/main.yml
    # future (spec 2026-06-26): otel_agent/  hw_exporter/
  files/  collections/installed/…(vendored, + community.general if adopted)
  molecule/            # OPTIONAL: default scenario per role (check-mode/converge)
```

`tasks/bootstrap/*.yml` are **deleted** once their content lives in roles.

---

## 5. Efficiency & idempotency findings (concrete, with fixes)

Ordered by severity. Line numbers are approximate (from the current files).

### High severity

1. **`roles/node_exporter` `meta: end_play` aborts the entire play** — `tasks/linux.yml` L8–10, `tasks/macos.yml` L8–10. `end_play` stops the play for **all** hosts once any one host is already running node_exporter. **Fix:** delete this role body; in the canonical role gate installation on a version/registered check per host (`when:`), never `end_play`. (lint: logic bug, not a lint rule.)
2. **salt_master service tasks force restart every run** — `tasks/service_systemd.yml` L3–17 and `tasks/service_macos.yml` (`state: restarted` + manual `launchctl unload/load`). This restarts salt-master/salt-api on **every** apply even when nothing changed, contradicting the role README's idempotency claim and causing needless fleet control-plane blips. **Fix:** use `state: started, enabled: true` and let the existing `handlers` perform restarts only when `configure.yml`/`api_tls.yml` notify them. (lint: `no-handler`/idempotency.)
3. **node_exporter downloads have no checksum** — `roles/node_exporter/tasks/{linux,macos}.yml` L12–16, and `tasks/bootstrap/node_exporter_*.yml` L28–34. Supply-chain risk. **Fix:** add `get_url: checksum: "sha256:{{ … }}"` (node_exporter publishes `sha256sums`), removing the need for any shell verify. (lint: security.)
4. **Hardcoded architecture** — `roles/node_exporter/tasks/linux.yml` L14 (`linux-amd64`), `macos.yml` L14 (`darwin-arm64`), and `salt_master/tasks/install_macos.yml` L13 (`arm64` pkg). Breaks Intel/ARM cross-cases. **Fix:** derive from `ne_arch`/`cpu_arch` (already computed by `common`).
5. **Duplicated salt-minion install logic** — `bootstrap_node.yml` L130–222 (macOS) + `tasks/bootstrap/minion_linux.yml` duplicate `salt_master/tasks/install_{macos,debian,redhat}.yml`. Two sources of truth for salt install/version-pinning. **Fix:** single `salt_minion` role; `salt_master` can even reuse the same download/verify task file.

### Medium severity

6. **`shell`/`command` where a module exists** (`command-instead-of-module`):
   - `tasks/bootstrap/node_deps.yml` L64–112 — `brew list`/`brew install` for macmon/tart → **`community.general.homebrew`** (idempotent, gives real `changed`). L34–35 pip → **`ansible.builtin.pip` (extra_args: --user)**.
   - `node_exporter_*.yml` L36–42 — `tar`/`cp`/`chmod` in shell → **`ansible.builtin.unarchive`** + `ansible.builtin.copy`.
   - `bootstrap_node.yml` L347–408 — `sw_vers`, `sysctl hw.logicalcpu`, `sysctl hw.memsize` (via python3!), `hw.model` collected by shell, but `setup:` (L43, `gather_subset: hardware`) already provides `ansible_memtotal_mb`, `ansible_processor_*`, `ansible_distribution_version`, `ansible_product_*`. **Fix:** use facts; keep shell only for genuinely macOS-specific bits (serial via `system_profiler`).
   - `redeploy_kri.yml` L49 `cat VERSION` → `ansible.builtin.slurp` or `command` with `changed_when: false`.
7. **`risky-shell-pipe` / fragile pipelines:**
   - `bootstrap_node.yml` L311 `ps aux | grep -v grep | grep salt-minion` → `ansible.builtin.wait_for` on the process, or `service_facts`, or `pipefail`. 
   - `node_exporter_*.yml` L22 `--version 2>&1 | head -1 | awk` → set `set -o pipefail` via `args: executable`, or capture then filter in Jinja.
8. **Missing `changed_when` / always-changed tasks** (`no-changed-when`):
   - `redeploy_kri.yml` L23 (`git pull`), L33 (`docker compose … --build`) always report `changed`. Add `changed_when` keyed on stdout ("Already up to date." / "Recreating"/"Building").
   - `bootstrap_node.yml` L116 CLT install `changed_when: clt_install.rc == 0` is effectively always-changed when the branch runs; key it on softwareupdate output instead.
9. **Duplicated grains-push `uri` blocks** — `bootstrap_node.yml` L452 (macOS) and L490 (Linux) are the same request with an OS-shaped body. **Fix:** one task with an OS-conditional `body` dict in `kri_enroll`. (spec §8.)
10. **Repeated check-then-install pairs** (`use-loop`) — `node_deps.yml` macmon/tart, and `bootstrap_node.yml` `/etc/salt*` dir creations (L230, L239) → single `loop` / `homebrew: name: [macmon, tart]`.
11. **Two separate reachability `nc` loops** — `bootstrap_node.yml` L61–91 checks 4505 and 4506 in two shell loops, then does a fragile `.index(item)` correlation (L82). **Fix:** one `ansible.builtin.wait_for` loop over `salt_masters × [4505,4506]`, or `product`. Also `nc` may be absent on minimal hosts — `wait_for` needs no external binary.

### Low severity / hygiene

12. **FQCN everywhere** (`fqcn[action-core]`) — nearly all tasks use bare `file`, `copy`, `template`, `get_url`, `systemd`, `command`, `shell`, `set_fact`, `uri`, `user`, `group`, `stat`, `slurp`, `unarchive`, `wait_for`, `find`, `fail`, `debug`. Convert to `ansible.builtin.*` (handlers already do this in `salt_master`). `ansible-lint --fix` handles most.
13. **`deprecated-local-action`** — `salt_master/tasks/install_macos.yml` L57, L94 use `local_action:`; convert to `delegate_to: localhost` (as `pki.yml` already does).
14. **No `meta/main.yml`** in either existing role (`role-name`/galaxy hygiene; `meta-no-dependencies` wants an empty `dependencies: []`). Add `meta/main.yml` (galaxy_info + `dependencies: []`) and, ideally, `meta/argument_specs.yml` to validate required inputs (`salt_masters`, `minion_id`, `kri_salt_api_password`).
15. **Non-deterministic UID** — `salt_master/tasks/api_user.yml` L16 `800 + RANDOM % 100` can collide across re-runs/hosts. **Fix:** pick a fixed UID or let the OS allocate a role account deterministically.
16. **`validate_certs: false`** on Artifactory `get_url` (`install_macos.yml` L45, `install_linux_onedir.yml` L53) — document/justify or fix the mirror's TLS.
17. **Risky default secret** — `deploy_salt_master_mm1.yml` L22 `kri_salt_api_password: "changeme-set-via-e-flag"`. Remove the default; fail fast if unset (like `install_salt_master.yml` does for `target_host`).
18. **`ansible.cfg`** — consider re-enabling `deprecation_warnings` in a lint/CI context; keep the runtime-quiet default for the worker.
19. **Broad `failed_when: false`** across bootstrap swallows real errors (e.g. grains push, salt schedules). Keep for genuinely best-effort steps, but let `kri_enroll` surface a summary of what failed rather than silently passing.
20. **Tags** — add role/task tags (`salt`, `telemetry`, `exporter`, `api`) so operators can run partial converges (`--tags api`), matching the spec's "salt-api is a tagged sub-step of master."

---

## 6. Phased migration plan (low-risk first)

Each phase is independently shippable, keeps existing filenames working, and is verified before the next. All verification uses `scripts/kri` where possible plus `ansible-playbook --syntax-check`, `ansible-lint`, and `--check` dry-runs.

**Phase 0 — Safety net & tooling (no behavior change).**
- Add `playbooks/requirements.yml` pinning `ansible.posix` and (if homebrew module adopted) `community.general`; vendor into `collections/installed`.
- Add `.ansible-lint` using the `production` profile with a documented `skip_list` for anything intentionally deferred.
- Baseline: run `ansible-lint playbooks/` and `ansible-playbook --syntax-check` on every playbook; record the current violation count as the regression baseline.
- Verify: `scripts/kri test unit` (ensure `playbook_discovery`/`playbook_tasks` tests still pass); no runtime change.
- Rollback: delete the added files.

**Phase 1 — Kill the drift: canonical `node_exporter` role.** *(highest value, isolated)*
- Replace `roles/node_exporter` body with the strong `tasks/bootstrap/node_exporter_*.yml` logic (arch-aware, checksum, dedicated user, handler), split into `tasks/{main,install,service_systemd,service_launchd}.yml` + templates. Remove `meta: end_play`.
- Keep `defaults/main.yml` back-compat: accept both `node_exporter_port`+`node_exporter_install_dir` (legacy) and `node_exporter_listen_address` (new), mapping legacy → new.
- `deploy_node_exporter.yml` filename unchanged.
- Verify: `ansible-playbook --syntax-check deploy_node_exporter.yml`; `ansible-lint roles/node_exporter`; `--check` run against one Linux + one macOS node via `scripts/kri` playbook run; confirm re-run is a no-op (0 changed).
- Rollback: git revert the role dir (filename/interface unchanged, so no library/job breakage).

**Phase 2 — Extract `common` + `node_telemetry` + `kri_enroll`.**
- Create `common` (arch/OS facts), `node_telemetry` (node_deps → homebrew/pip modules + loop), `kri_enroll` (deduped grains push + salt schedules).
- Do **not** yet rewire `bootstrap_node.yml`; unit-test the roles standalone via the worker's role-run path (`roles/node_telemetry`) in `--check`.
- Verify: `ansible-lint` each new role; standalone `--check` role run on one node each OS; idempotency re-run.
- Rollback: delete new role dirs (bootstrap untouched).

**Phase 3 — `salt_minion` role + thin `bootstrap_node.yml`.** *(riskiest — the monolith)*
- Move salt-minion install/config/service into `salt_minion` (macOS `.pkg`, Debian, RedHat, `minion.conf.j2`, HA failover, pubkey pre-seed).
- Rewrite `bootstrap_node.yml` as the orchestrator in §3.1, keeping the **same filename** and the same required extravars (`salt_masters`, `salt_master_pub_key`, `minion_id`, `ingest_url`, `node_token`) so worker calls and the BootstrapModal are unchanged.
- Verify: `--syntax-check`; `ansible-lint`; **full end-to-end bootstrap on one real macOS node and one real Linux node** (per spec §10) before any fleet rollout; confirm minion connects, grains land in kri, schedules apply, re-run idempotent.
- Rollback: `bootstrap_node.yml` is a single file — git revert restores the monolith; `salt_minion` role can remain unused.

**Phase 4 — Consolidate salt-master playbooks + role idempotency fixes.**
- Fix `salt_master` service tasks (handler-driven restarts, no forced `state: restarted`), FQCN, `local_action`→`delegate_to`, deterministic UID, `meta/main.yml`, arch fix, `get_url checksum`.
- Make `install_salt_master.yml` the single OS-conditional master playbook; turn `install_salt_master_linux.yml`, `setup_salt_master.yml`, `deploy_salt_master_mm1.yml` into **`import_playbook` shims** (preserve filenames for saved jobs/library) that call it. Fold the pillar-export `pre` plays into the canonical file behind a `when: legacy_docker_export | default(false)` gate.
- Coordinate: check the Playbook-Library / `ansible_job` rows and `playbook_catalog_svc` for references to the retired filenames; either keep shims indefinitely or run a one-time DB update to repoint them. **Decide with the user before deleting any filename.**
- Verify: `--syntax-check` all four; `ansible-lint roles/salt_master`; **re-apply against mm1** and confirm 0 restarts when config unchanged (the idempotency regression this phase fixes); salt-api `/login` verify probe still green.
- Rollback: revert; shims mean no external reference breaks.

**Phase 5 — Cleanup & polish.**
- Delete `tasks/bootstrap/*.yml` (now empty of unique logic).
- `redeploy_kri.yml` idempotency fixes (`changed_when`, slurp VERSION).
- Add tags across roles; optional `molecule/` default scenarios for `salt_minion`, `node_exporter`, `node_telemetry`.
- Verify: full `ansible-lint playbooks/` against the `production` profile meets the agreed threshold; `scripts/kri test unit` green; `scripts/kri` discovery lists all expected playbooks/roles.
- Merge gate: full test suite per CLAUDE.md, not per-agent.

---

## 7. Verification commands (per phase)

```bash
# syntax + lint (from repo root; ANSIBLE_CONFIG resolves to playbooks/ansible.cfg)
ansible-playbook --syntax-check playbooks/<playbook>.yml -i playbooks/inventory/hosts.ini
ANSIBLE_ROLES_PATH=playbooks/roles ansible-lint -p production playbooks/

# dry-run against a real node (no changes applied)
ansible-playbook playbooks/deploy_node_exporter.yml -i <ip>, -e target_host=<ip> --check --diff

# idempotency: run twice, second run must report 0 changed
# via the platform (exercises the real worker path):
scripts/kri  # (playbook run through kri Automation Hub / CLI)

# unit tests for the discovery/runner glue that parses roles+defaults
scripts/kri test unit   # includes tests for playbook_discovery / playbook_tasks
```

---

## 8. Risks & open questions

**Risks**
- **Filename references.** Retiring `setup_salt_master.yml` / `install_salt_master_linux.yml` / `deploy_salt_master_mm1.yml` can break saved `ansible_job` rows, scheduled runs, and Playbook-Library entries that store the filename. Mitigation: keep `import_playbook` shims (recommended) and/or a one-time DB repoint.
- **Bootstrap monolith rewrite (Phase 3)** is the highest-risk change — it touches the live node-enrollment path. Mitigation: keep extravars contract identical; gate rollout on a real macOS + Linux e2e bootstrap.
- **Adopting `community.general.homebrew`** requires vendoring that collection into `collections/installed`; otherwise the `#357` pre-flight fails the run. If we don't want the dependency, keep brew via `shell` but add `changed_when`/`creates` guards instead.
- **salt_master idempotency fix** changes restart behavior; verify the salt-api ACL still reloads when `kri.conf`/`salt-api.conf` change (handlers must fire on config change — they already `notify`, so this is safe once forced restarts are removed).
- **macOS launchd quirks** (documented in the code: `salt-minion --version` hangs; use `pkgutil`) must be preserved verbatim in `salt_minion`.

**Open questions for the user**
1. Retire the 3 duplicate salt-master playbook filenames via **shims** (zero breakage, slightly more files) or **delete + DB migration** (cleaner tree, needs a coordinated update)? Recommendation: shims now, delete later.
2. OK to vendor **`community.general`** for `homebrew`/`pip` idempotency, or keep brew/pip as guarded `shell`?
3. Should `node_exporter` be **off by default** in bootstrap (per the 2026-06-26 spec's OTel-first direction), or preserve today's always-install behavior until `otel_agent` lands?
4. Standardize the consolidated master playbook on `hosts: all` (worker `[targets]`-friendly) and drop the `hosts: "{{ target_host }}"` form?
5. Adopt **Molecule** for role CI now, or defer (adds dev-dep + CI time)?
6. Target `ansible-lint` **`production`** profile as the CI gate, or start at `safety`/`shared` and ratchet up?
```