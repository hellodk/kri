# Ansible Tree Audit — Redundancy, Bootstrap-Scoping, Optimization

**Scope:** `playbooks/` (all top-level `*.yml`, `tasks/`, `roles/`, `group_vars/`, `host_vars/`, `inventory/`, `ansible.cfg`). `playbooks/collections/installed/` (vendored upstream) is out of scope.
**Method:** every file read in full; every claim below is grounded in file:line evidence. Cross-checked against live invocation code (`fleet_platform/workers/playbook_tasks.py`, `fleet_platform/workers/ansible_tasks.py`, `fleet_platform/services/playbook_discovery.py`, `fleet_platform/api/routes/ansible/_router.py`, `scripts/kri`) so recommendations don't break what's actually wired up.
**Reconciled with:** `docs/ANSIBLE_REVIEW.md` (2026 gap review), `docs/superpowers/specs/2026-06-26-ansible-role-consolidation-design.md` (target design), `docs/superpowers/plans/2026-07-05-ansible-roles-refactor-plan.md` (phased execution plan). This document does not repeat their content — it verifies it against the current tree, adds file:line evidence the prior docs stated as "approximate," and corrects one load-bearing assumption (see §2.1).

---

## 0. Invocation ground truth (read first — changes prior assumptions)

Confirmed by reading the actual call sites, not inferred:

| Playbook | Called by | Evidence |
|---|---|---|
| `bootstrap_node.yml` | **Only** entry point for node bootstrap. Hard-gated: `_BOOTSTRAP_ONLY_PLAYBOOKS = frozenset({"bootstrap_node.yml"})` blocks it from the generic run API — it must go through the dedicated bootstrap endpoint. | `fleet_platform/api/routes/ansible/_router.py:13`; `fleet_platform/workers/ansible_tasks.py:340` |
| `install_salt_master.yml` (macOS) / `install_salt_master_linux.yml` (Linux) | **Live**, OS-dispatched by the `provision_master` Celery task (#557) via a lookup table, AND by `scripts/kri saltmaster install` (same table, comment says "SSoT #561"). | `fleet_platform/workers/ansible_tasks.py:688-691` (`_MASTER_PLAYBOOKS = {"Darwin": "install_salt_master.yml", "Linux": "install_salt_master_linux.yml"}`); `scripts/kri:828-863` |
| `deploy_salt_master_mm1.yml` | **Not referenced anywhere** in `fleet_platform/` or `scripts/kri`. | `grep -rn` returned zero hits outside the file itself |
| `setup_salt_master.yml` | **Not referenced anywhere** in `fleet_platform/` or `scripts/kri`. | same |
| `deploy_node_exporter.yml` / `redeploy_kri.yml` | Not referenced by name in app code — reachable only via the generic Automation Hub run path (`playbook_discovery.discover_all` walks `playbooks/` and lists every top-level `*.yml`). | `fleet_platform/services/playbook_discovery.py:106-134` |
| `inventory/dynamic.py` | **Not referenced anywhere** — no `-i inventory/dynamic.py` in any script, worker, or doc. | `grep -rn` zero hits |
| `group_vars/home.yml` | **Orphaned** — byte-identical to `host_vars/mm1.yml` (`diff` = no output), but `inventory/hosts.ini` defines no `[home]` group, so this file is never loaded by any inventory. | `diff playbooks/host_vars/mm1.yml playbooks/group_vars/home.yml` → empty |

**Correction to the prior design docs:** both prior documents (refactor plan §2.1, consolidation design §4) describe all four salt-master playbooks as "near-duplicate wrappers" of equal standing and propose collapsing all four into one file with shims for the retired names. That's **half right**: `deploy_salt_master_mm1.yml` and `setup_salt_master.yml` are genuinely dead (zero call sites) and can be deleted outright — no shim needed, nothing references their filenames. But `install_salt_master.yml` / `install_salt_master_linux.yml` are **not interchangeable duplicates** — they are the two branches of a live OS-dispatch table (`_MASTER_PLAYBOOKS`) baked into `ansible_tasks.py:688-691` and `scripts/kri:830-862`. Merging them into one OS-conditional playbook (as both prior docs propose) is still valid, but it requires editing `_MASTER_PLAYBOOKS` and the `scripts/kri` case block in the same change — it is a **code change**, not a playbook-only refactor, and the "keep old filename as a shim" mitigation the plan proposes for filename-safety doesn't apply here (the filenames are read from a Python dict literal, not a DB row) so there is no "saved job breaks" risk for these two specifically. There is a risk only if the merged file changes required extravars or `hosts:` targeting in a way `provision_master` doesn't already pass.

---

## 1. Inventory of every file

| File | Purpose | Verdict | Reason |
|---|---|---|---|
| `ansible.cfg` | Runner config (`forks=20`, `pipelining`, `task_timeout=300`, `host_key_checking=False`) | KEEP | Sane worker-oriented defaults; no issues found |
| `requirements.yml` | Pins `ansible.posix>=2.0.0` | KEEP | Correct, minimal |
| `bootstrap_node.yml` | 534-line monolith: arch/OS detect, master-reachability gate, Xcode CLT, minion install+config+start, authorized_keys, VNC, grains collection, node_deps, heartbeat/process schedules, grains push ×2, node_exporter ×2 | REFACTOR | Sole bootstrap entry point (§0) — highest-value target for the roles split already planned in the two prior docs; ~10 concerns in one play |
| `install_salt_master.yml` | Install salt-master on macOS (air-gapped `.pkg`) + legacy Docker pillar export | KEEP (consolidate later) | Live via `_MASTER_PLAYBOOKS["Darwin"]` (§0) — not safe to delete without an `ansible_tasks.py` code change |
| `install_salt_master_linux.yml` | Install salt-master on Linux (apt/yum) | KEEP (consolidate later) | Live via `_MASTER_PLAYBOOKS["Linux"]` (§0) |
| `deploy_salt_master_mm1.yml` | Install salt-master via `hosts: all`, hardcoded default password | DELETE | Zero call sites (§0); superseded by `install_salt_master.yml`; risky default `kri_salt_api_password: "changeme-set-via-e-flag"` (line 22) |
| `setup_salt_master.yml` | Install salt-master on mm1 + Docker pillar-export pre-play | DELETE | Zero call sites (§0); pillar-export duplicate of `install_salt_master.yml`'s own pre-play (lines 77-100) and of `roles/salt_master/tasks/pillar.yml:44-56` |
| `deploy_node_exporter.yml` | `roles: [node_exporter]` against `targets` | KEEP shape / FIX target | Thin and correctly shaped, but points at the **weak, drifted** `roles/node_exporter` body (§2) |
| `redeploy_kri.yml` | git pull + docker compose rebuild + health check on the kri host itself | KEEP (not bootstrap) | Legitimate kri-redeploy playbook, ops-only; idempotency fixes needed (§4) |
| `files/salt-3007.14-py3-arm64.pkg` (+ `.sha512`) | Bundled air-gap installer used by `install_salt_master.yml`'s pre-flight (`install_salt_master.yml:54-74`) | KEEP | Actively consumed |
| `group_vars/all.yml` | Shared defaults: salt version, URLs, brew prefixes, node_exporter version, Artifactory layout | KEEP | Well-documented, single source for most defaults |
| `group_vars/home.yml` | Byte-identical copy of `host_vars/mm1.yml` | DELETE | Orphaned — no `[home]` inventory group exists (§0); dead weight that will silently diverge from `host_vars/mm1.yml` over time |
| `host_vars/mm1.yml` | Per-host become/ssh vars for mm1 | KEEP | Loaded by the `[fleet]`/`[salt_master]` groups in `hosts.ini` |
| `inventory/hosts.ini` | Static groups: `salt_master`, `fleet`, `kri_host`, `targets` | KEEP | Reference file for manual runs; worker generates its own inventory (`_write_static_inventory`) |
| `inventory/dynamic.py` | Minimal dynamic inventory reading `TARGET_HOST`/`ANSIBLE_USER`/`ANSIBLE_PASSWORD` env vars | DELETE | Zero references anywhere in the codebase (§0) — dead code; also has no `#!/usr/bin/env python3` executable bit check and no error handling if `TARGET_HOST` is unset |
| `roles/salt_master/defaults/main.yml` | Role defaults + `_kri_var_descriptions` | KEEP | Correct, well-documented |
| `roles/salt_master/handlers/main.yml` | 8 handlers (4 macOS launchctl, 4 Linux systemd), OS-gated via `when:` on the same `listen:` name | KEEP | Correctly OS-split (this file already does what `docs/ANSIBLE_REVIEW.md` Gap 4 asked for — that gap appears already fixed since the 2026-05 review; see §2.3) |
| `roles/salt_master/README.md` | Role documentation | KEEP | Accurate against current task files (verified line-by-line) |
| `roles/salt_master/tasks/main.yml` | OS-gate → install → configure → pki → pillar → states → api_user → api_tls → service → verify → minion | KEEP | Clean orchestration |
| `roles/salt_master/tasks/install_macos.yml` | 3-tier download (Artifactory/local bundle/official) + pkgutil version gate + install | KEEP | Strong impl, matches `docs/ANSIBLE_REVIEW.md` §1 praise; stale header comment (line 2 says "install.yml", file is macOS-specific) — cosmetic only |
| `roles/salt_master/tasks/install_debian.yml` | apt install `salt-master` + `salt-api` | KEEP | Already installs both packages — **contradicts** `docs/ANSIBLE_REVIEW.md` Gap 2, which is stale (see §2.3) |
| `roles/salt_master/tasks/install_redhat.yml` | dnf install `salt-master` + `salt-api` | KEEP | Same — Gap 2 already fixed |
| `roles/salt_master/tasks/install_linux_onedir.yml` | Air-gapped Linux onedir tarball install (3-tier download, checksum, symlinks) | KEEP | New since the 2026-05 review (marked `#696`, "LIVE-ENVIRONMENT VALIDATION NEEDED" at lines 23-28) — functionally solid but **unvalidated in production**; flag for a smoke test before relying on it |
| `roles/salt_master/tasks/configure.yml` | Writes `kri.conf` + `salt-api.conf`, notifies restart handlers | KEEP | `group: "{{ 'wheel' if ansible_system == 'Darwin' else 'root' }}"` already OS-conditional at every occurrence (lines 9,18,27,39,49) — **contradicts** `docs/ANSIBLE_REVIEW.md` Gap 8, stale (§2.3) |
| `roles/salt_master/tasks/api_user.yml` | macOS `sysadminctl`/`dscl` branch + Linux `group`/`user`/`chpasswd` branch, both gated on `_salt_os` | KEEP | Linux branch now exists — **contradicts** Gap 1, stale (§2.3). Non-deterministic `UniqueID "$(( 800 + RANDOM % 100 ))"` at line 16 remains a real, live issue (§4) |
| `roles/salt_master/tasks/api_tls.yml` | Self-signed cert/key via `openssl req`, `creates:` guard | KEEP | Correctly idempotent |
| `roles/salt_master/tasks/pki.yml` | Transfers pre-provisioned master keypair from controller via `slurp`, best-effort | KEEP | Well-reasoned (see inline comments lines 26-50); hardcodes `group: wheel` unconditionally (lines 11, 73, 82, 91) — Linux-breaking bug, not yet caught by prior reviews (§4, new finding) |
| `roles/salt_master/tasks/pillar.yml` | Pillar dir + top.sls + match_id.sls + sync from controller export | KEEP | `group: wheel` hardcoded (lines 10, 24, 40, 52) — same new finding as pki.yml; `failed_when: false` on sync (line 56) matches Gap 6 (already known) |
| `roles/salt_master/tasks/states.yml` | Copies `salt/states/` to master | KEEP | `group: wheel` hardcoded (lines 9, 21) — same new finding |
| `roles/salt_master/tasks/service_macos.yml` | Writes plists + unconditional `launchctl load/start` block + `wait_for` + `salt-key -L` | REFACTOR | Confirms Gap 5 / plan finding #2 — unconditional restart block (lines 24-53) still present, contradicts README's "no-op re-apply" claim (README.md:65) |
| `roles/salt_master/tasks/service_systemd.yml` | `systemd: state: restarted` unconditionally for both services | REFACTOR | Confirms plan finding #2 — **more severe than documented**: both tasks force `state: restarted` (lines 7, 15) on every run, no `failed_when: false` fallback anymore (the Gap 2 "salt-api absent" case no longer applies since install now includes salt-api) |
| `roles/salt_master/tasks/verify.yml` | `wait_for` both ports + `/login` eauth probe | KEEP | Meaningful integration check, confirmed still accurate |
| `roles/salt_master/tasks/minion.yml` | Co-locates a minion on the master, points at `127.0.0.1`, accepts its own key | KEEP | New since 2026-05 review (#707); logic is sound; duplicates minion-install concepts already in `bootstrap_node.yml` conceptually (not code) — acceptable, this is co-location not fleet-bootstrap |
| `roles/salt_master/templates/kri-master.conf.j2` | Master config: ACL, netapi clients, reactor, pillar/file roots | KEEP | ACL correctly scoped (no `cmd.run`, comment at line 92 documents the #758 removal) |
| `roles/salt_master/templates/salt-api.conf.j2` | `rest_cherrypy` TLS config | KEEP | Minimal, correct |
| `roles/salt_master/templates/salt-master.plist.j2` | macOS launchd unit for salt-master | KEEP | Correct |
| `roles/salt_master/templates/salt-api.plist.j2` | macOS launchd unit for salt-api, raises open-file limit | KEEP | Good — documents a real production bug fix (comment lines 27-31) |
| `roles/node_exporter/defaults/main.yml` | `node_exporter_port`, `node_exporter_install_dir`, `node_exporter_user` (unused) | REFACTOR/DELETE-BODY | Incompatible variable scheme vs. what the app actually sends (§2.2) |
| `roles/node_exporter/handlers/main.yml` | macOS-only `launchctl kickstart` handler | REFACTOR/DELETE-BODY | No Linux handler; role never `notify`s it anyway (tasks use `ignore_errors`/unconditional `command`, not `notify`) |
| `roles/node_exporter/tasks/main.yml` | `import_tasks` linux.yml/macos.yml gated on `ansible_system` | REFACTOR/DELETE-BODY | Shape is fine; both children are the drifted implementation |
| `roles/node_exporter/tasks/linux.yml` | Download (no checksum, hardcoded `linux-amd64`), install, systemd unit, **`meta: end_play`** | DELETE-BODY | Confirmed live bug: `meta: end_play` at line 9 aborts the **entire play for every host** the instant one host already has node_exporter running (§2.2, §4) |
| `roles/node_exporter/tasks/macos.yml` | Download (no checksum, hardcoded `darwin-arm64`), install, launchd, **`meta: end_play`** | DELETE-BODY | Same `end_play` bug at line 9; runs as root (no dedicated user), unlike the bootstrap-task macOS variant which also runs as root but at least matches the canonical arch/URL scheme |
| `tasks/bootstrap/minion_linux.yml` | apt/yum install of `salt-minion` (not `salt-master`) | MERGE | Duplicate *pattern* (not identical code) of `roles/salt_master/tasks/install_debian.yml` / `install_redhat.yml` — same repo-key/apt-source/install shape, different package name (§2.2) |
| `tasks/bootstrap/node_deps.yml` | psutil (both OS) + macmon/tart (macOS, Homebrew) | KEEP (optimize) | Unique content, not duplicated elsewhere; repeated check-then-install pairs should loop (§4) |
| `tasks/bootstrap/node_exporter_linux.yml` | Arch-aware URL, Artifactory-aware, checksum-less, dedicated `node_exporter` system user, systemd unit | KEEP — this is the **canonical** impl | Confirmed this is what the live app actually parameterizes (`node_exporter_listen_address`, `node_exporter_url_override` match `ansible_tasks.py:333-338`) — §2.2 |
| `tasks/bootstrap/node_exporter_macos.yml` | Arch-aware URL, Artifactory-aware, launchd, runs as root | KEEP — canonical for macOS | Same var scheme as the Linux sibling; only gap is running as root instead of a dedicated user (macOS has no simple system-account equivalent used here) |

---

## 2. Redundant / duplicate files

### 2.1 Salt-master wrapper playbooks — corrected verdict (see §0)

| File | Status | Action |
|---|---|---|
| `install_salt_master.yml` | Live (macOS branch of `_MASTER_PLAYBOOKS`) | Keep as-is short term; long-term merge into one OS-conditional file **and** update `ansible_tasks.py:688-691` + `scripts/kri:847,860` in the same PR |
| `install_salt_master_linux.yml` | Live (Linux branch) | Same |
| `deploy_salt_master_mm1.yml` | Dead — zero call sites | **Delete now**, no shim needed (nothing addresses it by filename) |
| `setup_salt_master.yml` | Dead — zero call sites | **Delete now**, no shim needed |

Both dead files independently duplicate the same three concerns already present in the live files: Docker-pillar export (`install_salt_master.yml:77-100` vs `setup_salt_master.yml:18-44` vs implicit skip in `deploy_salt_master_mm1.yml`), `roles: [salt_master]` invocation, and a `.env.docker` post-install instructions blob. `roles/salt_master/tasks/pillar.yml:44-56` already does the controller→target sync generically (reading whatever `/tmp/kri-pillar-export/` contains) — so the pre-play in `install_salt_master.yml:77-100` is itself redundant with what the two dead files also do; once `deploy_salt_master_mm1.yml`/`setup_salt_master.yml` are deleted, keep exactly one copy of the pillar-export pre-play (`install_salt_master.yml`'s) and consider making it a `tasks/legacy_pillar_export.yml` include shared by both live playbooks, gated `when: legacy_docker_export | default(false)` (as the 2026-07-05 plan already proposes at line 252).

### 2.2 node_exporter implemented twice, confirmed still drifted and confirmed which one is live

Verified byte-for-byte against the 2026-06-26 design doc's claim — still true today:

| | `roles/node_exporter/tasks/{linux,macos}.yml` | `tasks/bootstrap/node_exporter_{linux,macos}.yml` |
|---|---|---|
| Arch handling | Hardcoded `linux-amd64` (`roles/node_exporter/tasks/linux.yml:14`), hardcoded `darwin-arm64` (`macos.yml:14`) | Arch-aware via `ne_arch` fact (`node_exporter_linux.yml:8`, `node_exporter_macos.yml:8`) |
| Download source | GitHub only | Artifactory → override → official, 3-tier (`node_exporter_linux.yml:13-19`) |
| Checksum | None either file | None either file (also missing — see §4 High-1) |
| Idempotency gate | `meta: end_play` (`linux.yml:9`, `macos.yml:9`) — **aborts entire multi-host play** | Version comparison `when: ne_installed_version.stdout.strip() != node_exporter_version` (`node_exporter_linux.yml:34`, `node_exporter_macos.yml:34`) — correct per-host gate |
| Variable names | `node_exporter_port`, `node_exporter_install_dir` (`roles/node_exporter/defaults/main.yml:3-5`) | `node_exporter_listen_address`, hardcoded `/usr/local/bin` (`node_exporter_linux.yml:72`) |
| Run-as user | root (both) | Dedicated `node_exporter` system user (Linux only: `node_exporter_linux.yml:44-57`); macOS still root |
| **Which one the app actually drives** | Only reachable via `deploy_node_exporter.yml` (Automation Hub manual run) | **This is the one `provision`/bootstrap actually parameterizes** — `ansible_tasks.py:93-95,333-338` pass `node_exporter_version`, `node_exporter_listen_address`, `node_exporter_url_override`, which match this file's variable names exactly, not the role's |

**Conclusion (unchanged from the design doc, now confirmed against live extravars):** `tasks/bootstrap/node_exporter_{linux,macos}.yml` is canonical. `roles/node_exporter` is the dead/wrong-vars branch that only fires when an operator manually runs `deploy_node_exporter.yml` from the Library — and when they do, they get the weaker, buggy (`end_play`), unparameterizable implementation. **Action:** replace `roles/node_exporter/tasks/{linux,macos}.yml` bodies with the canonical logic (delete `meta: end_play`, add per-host version gate, unify variable names), per the design doc's Phase 1. This is the single highest-value, lowest-risk fix in this audit — isolated to one role directory, `deploy_node_exporter.yml`'s filename/interface (`roles: [node_exporter]`) doesn't change.

### 2.3 Prior review (`docs/ANSIBLE_REVIEW.md`) — items already fixed since it was written

Verified against current code; these five items are stale and should be marked resolved (not re-opened as new work):

| Prior Gap | Claim | Current state |
|---|---|---|
| Gap 1 | `api_user.yml` runs macOS-only commands on Linux unconditionally | **Fixed** — `api_user.yml:5,29` gates the macOS block on `when: _salt_os == 'macos'`; lines 32-57 add a full Linux `group`/`user`/`chpasswd` branch gated `when: _salt_os != 'macos'` |
| Gap 2 | Linux installers don't install `salt-api`; `service_systemd.yml` masks it with `failed_when: false` | **Fixed** — `install_debian.yml:24-31` and `install_redhat.yml:13-19` both install `salt-api` alongside `salt-master`; current `service_systemd.yml` has no `failed_when: false` at all (it now unconditionally restarts both — see §4 High-2, a different, still-open bug) |
| Gap 4 | Handlers are macOS-only, notified cross-platform incorrectly | **Fixed** — `handlers/main.yml` has 8 handlers, each `listen:`-paired (macOS `shell`+`launchctl` gated `when: ansible_system == 'Darwin'`, Linux `ansible.builtin.systemd` gated `when: ansible_system != 'Darwin'`) sharing the same `listen:` name so `notify:` fires the right one per OS |
| Gap 8 | `configure.yml` hardcodes `group: wheel` on all OSes | **Fixed** — every occurrence in `configure.yml` (lines 9, 18, 27, 39, 49) uses `group: "{{ 'wheel' if ansible_system == 'Darwin' else 'root' }}"` |
| Gap 13 | `roles/node_exporter` uses `meta: end_play` | **Still open** — confirmed live at `roles/node_exporter/tasks/linux.yml:9` and `macos.yml:9`; see §2.2 and §4 High-1 |

**New finding not in either prior doc:** the `group: wheel` fix landed in `configure.yml` but was **not applied consistently** to three sibling task files in the same role — `pki.yml` (lines 11, 73, 82, 91), `pillar.yml` (lines 10, 24, 40, 52), and `states.yml` (lines 9, 21) all still hardcode `group: wheel` unconditionally, which does not exist on Debian/RHEL. Any Linux salt-master install will fail at PKI directory creation (`pki.yml:6-20`) — this is the same class of bug Gap 8 fixed in one file but missed in three others. See §4 High.

### 2.4 Duplicated grains-push blocks

`bootstrap_node.yml:452-487` (macOS) and `bootstrap_node.yml:490-524` (Linux) are two `uri: POST {{ ingest_url }}/grains` tasks with near-identical bodies — same headers, same `status_code`, same `no_log`/`failed_when: false`, differing only in which grains dict fields are populated from macOS-shell-collected facts vs. Ansible facts. Collapse into one task with an OS-conditional `body` dict (as both prior docs already recommend — design doc §8, plan finding #9). No change to recommendation; confirmed still present at these exact line ranges.

### 2.5 Duplicated salt-minion install logic

`tasks/bootstrap/minion_linux.yml` (apt/dnf install of `salt-minion`) is structurally identical to `roles/salt_master/tasks/install_debian.yml` / `install_redhat.yml` (apt/dnf install of `salt-master`+`salt-api`) — same keyrings-dir → repo-key → apt-source → package pattern, just a different package list. Two sources of truth for "how do we add the Salt apt/yum repo on this host." Confirmed at:
- `tasks/bootstrap/minion_linux.yml:9-31` (Debian block) vs `roles/salt_master/tasks/install_debian.yml:3-23` (repo setup, before the package install)
- `tasks/bootstrap/minion_linux.yml:42-51` (RedHat block) vs `roles/salt_master/tasks/install_redhat.yml:3-11`

Fix (unchanged from prior docs): extract the repo-setup steps into one shared task file parameterized by package list, consumed by both a future `salt_minion` role and `salt_master`'s installers.

### 2.6 Other redundancies not previously documented

- **`group_vars/home.yml` is a dead, byte-identical fork of `host_vars/mm1.yml`** (§0). Not mentioned in either prior doc. Delete — it is orphaned (no `[home]` group in `inventory/hosts.ini`) and would silently drift from `mm1.yml` if either were edited without the other.
- **`inventory/dynamic.py` is dead code**, referenced nowhere (§0). Neither prior doc flags it. Delete, or if it's meant as a documented manual-run helper, add a comment explaining intended usage and wire it into `scripts/kri` — currently it is neither used nor documented.
- **Repeated download/checksum/extract pattern**, present in four near-identical forms: `roles/salt_master/tasks/install_macos.yml:37-158`, `roles/salt_master/tasks/install_linux_onedir.yml:45-201`, `bootstrap_node.yml:146-222` (inline macOS minion download), and conceptually in `tasks/bootstrap/node_exporter_{linux,macos}.yml:28-42` (download+extract, no checksum). All four repeat: resolve URL by precedence tier → check installed version → download on controller → verify checksum (where present) → copy to target → install → clean up. This is the single largest volume of duplicated logic in the tree by line count. Both prior docs recommend a shared "resolve→check→download→verify→deploy" task file (design doc §8, last bullet) — confirmed still the right fix, still unimplemented.

---

## 3. "Restrict to bootstrap-related items only"

**What the worker's bootstrap path actually invokes**, confirmed from `_BOOTSTRAP_ONLY_PLAYBOOKS` (`_router.py:13`) and `ansible_tasks.py:340`: **only `bootstrap_node.yml`**, which in turn `include_tasks`s exactly four files: `tasks/bootstrap/minion_linux.yml`, `tasks/bootstrap/node_deps.yml`, `tasks/bootstrap/node_exporter_linux.yml`, `tasks/bootstrap/node_exporter_macos.yml` (lines 226, 415, 528, 532). Nothing under `roles/` is reachable from the bootstrap path — `bootstrap_node.yml` does not use `roles:` at all; the salt-minion, node_deps, and node_exporter logic is all inline `shell`/`copy`/`include_tasks`, never `roles/salt_master` or `roles/node_exporter`.

### Classification

| Playbook / role | Class | In scope for "bootstrap-only" tree? |
|---|---|---|
| `bootstrap_node.yml` | **bootstrap-path** | Yes — the only playbook the bootstrap endpoint runs |
| `tasks/bootstrap/minion_linux.yml` | bootstrap-path (included by bootstrap_node.yml) | Yes |
| `tasks/bootstrap/node_deps.yml` | bootstrap-path | Yes |
| `tasks/bootstrap/node_exporter_linux.yml` | bootstrap-path | Yes |
| `tasks/bootstrap/node_exporter_macos.yml` | bootstrap-path | Yes |
| `install_salt_master.yml` | master-provisioning | No — separate `provision_master` task/queue, a different lifecycle (`fleet_platform/workers/ansible_tasks.py:695-702`, `queue="ansible"` dedicated long-job queue) |
| `install_salt_master_linux.yml` | master-provisioning | No |
| `deploy_salt_master_mm1.yml` | master-provisioning (dead) | No — and should be deleted regardless (§2.1) |
| `setup_salt_master.yml` | master-provisioning (dead) | No — same |
| `roles/salt_master/**` | master-provisioning | No — only reached via the four master-install playbooks above, never by bootstrap |
| `deploy_node_exporter.yml` | misc / manual fleet-ops | No — Automation Hub only, not bootstrap, not master-provisioning |
| `roles/node_exporter/**` | misc (dead weight, see §2.2) | No |
| `redeploy_kri.yml` | kri-redeploy | No — operates on the kri host itself, unrelated to fleet nodes |
| `inventory/*`, `group_vars/*`, `host_vars/*`, `ansible.cfg`, `requirements.yml` | shared infrastructure | Partially — `ansible.cfg`, `requirements.yml`, and `group_vars/all.yml` are used by every playbook including bootstrap; `hosts.ini`/`host_vars/mm1.yml`/`group_vars/home.yml` are manual-run-only and master-provisioning-only |

### What "bootstrap-only" would concretely mean

If the user's intent is a tree scoped strictly to what fleet-node bootstrap needs, the **minimal set** is:

```
playbooks/
  ansible.cfg
  requirements.yml
  group_vars/all.yml           # only the vars bootstrap_node.yml reads: salt_version,
                                # salt_pkg_*, salt_deb_*/salt_rpm_* repo URLs,
                                # brew_prefix_*, node_exporter_version, artifactory_* URLs
  bootstrap_node.yml
  tasks/bootstrap/
    minion_linux.yml
    node_deps.yml
    node_exporter_linux.yml
    node_exporter_macos.yml
```

Everything else — `install_salt_master*.yml`, `deploy_salt_master_mm1.yml`, `setup_salt_master.yml`, `roles/salt_master/`, `deploy_node_exporter.yml`, `roles/node_exporter/`, `redeploy_kri.yml`, `inventory/hosts.ini`, `host_vars/mm1.yml`, `group_vars/home.yml` — is **master-provisioning, kri-redeploy, or manual-fleet-ops**, not bootstrap. This matches the design doc's own rule (§3, "a role is a reusable, cohesive installer; bootstrap-only orchestration glue stays in the playbook") but goes one step further: it says the master-provisioning tree and the bootstrap tree don't just have *different roles*, they are **operationally two different lifecycles already** (different Celery queues — `ansible_tasks.py:699` `queue="ansible"` dedicated to `provision_master`, vs. the bootstrap task's own queue) that happen to share a git directory.

**Concrete option if "restrict to bootstrap-only" means physically separating the tree:** move `install_salt_master*.yml` + `roles/salt_master/` + `deploy_salt_master_mm1.yml`/`setup_salt_master.yml` (post-delete) into a sibling directory, e.g. `playbooks/master-provisioning/`, and update `_get_playbooks_dir`/`playbook_sources` (already a multi-source-capable system per `fleet_platform/services/playbook_sources.py`) to register it as a second source. This is a **larger, riskier change** than the phased in-place refactor both prior docs propose, and is not recommended as a first step — the phased roles-split (Phase 0-5 in the 2026-07-05 plan) already achieves logical separation (which roles bootstrap touches vs. which it doesn't) without a directory-source migration. Recommend: **keep one directory, finish the roles-split, and treat this table as the definition of "bootstrap-only" for documentation/CLAUDE.md purposes** rather than a physical move, unless the user specifically wants the Automation Hub to stop listing master-provisioning playbooks in the same list as bootstrap ones.

---

## 4. Optimization findings (ordered by severity)

### High severity

**H1 — `roles/node_exporter` `meta: end_play` aborts the entire play, not just the current host.**
`playbooks/roles/node_exporter/tasks/linux.yml:8-10` and `tasks/macos.yml:8-10`:
```yaml
- name: Skip if already running
  meta: end_play
  when: svc_check.stdout == "active"   # (port_check.rc == 0 for macos.yml)
```
In a multi-host run of `deploy_node_exporter.yml` (`hosts: targets`, potentially many nodes), the **first** host where node_exporter is already active ends the play for **every remaining host in that batch**, silently skipping their install. Fix: delete the `meta: end_play` task; rely on the `when:` gates already present on the download/install tasks below it (or a `creates:`/version check per host, matching the canonical `tasks/bootstrap/node_exporter_*.yml` pattern).

**H2 — `service_systemd.yml` and `service_macos.yml` force a restart on every apply, contradicting the role's own documented idempotency guarantee.**
`roles/salt_master/tasks/service_systemd.yml:3-17` — both `systemd:` tasks use `state: restarted` unconditionally, with no `notify`-driven gate. `roles/salt_master/tasks/service_macos.yml:24-53` — `Load`/`Start` shell tasks run every time regardless of whether the plist changed (`changed_when: false` masks it from the changed-count, but the restart still executes). This directly contradicts `roles/salt_master/README.md:65`: "Running the role again when nothing has changed is a no-op — all tasks report `ok`, no handlers fire, no services restart." **Every apply currently restarts salt-master and salt-api**, causing a real control-plane blip on a homelab fleet each time the master-provisioning playbook runs (e.g. during a routine re-apply to pick up an unrelated config change). Fix: `state: started, enabled: true` in `service_systemd.yml`; delete the manual `launchctl load/start` block in `service_macos.yml:24-53` and rely solely on the `notify:`-driven handlers in `handlers/main.yml` (already correctly wired from `configure.yml`, `api_tls.yml`, and the plist `template:` tasks).

**H3 — Three task files in `roles/salt_master` hardcode `group: wheel`, breaking Linux installs — a fix applied in `configure.yml` was missed in siblings.**
`roles/salt_master/tasks/pki.yml:11,73,82,91`, `pillar.yml:10,24,40,52`, `states.yml:9,21` all use bare `group: wheel` with no OS conditional (unlike `configure.yml`, which correctly uses `group: "{{ 'wheel' if ansible_system == 'Darwin' else 'root' }}"` at every occurrence). `wheel` does not exist as a group on Debian/RHEL by default. Any Linux salt-master install will fail the very first PKI-directory-creation task (`pki.yml:6-20`, `loop:` over 6 directories) with "group wheel does not exist," before configure.yml even runs (main.yml orders `pki.yml` at line 54, before `pillar.yml`/`states.yml` at 55-56 — configure.yml at line 53 runs first and would succeed, masking the fact that pki.yml immediately after it fails). **This is currently a hard blocker for any Linux salt-master install** — worse than any gap in the prior review, which only found the (already-fixed) `configure.yml` instance. Fix: `sed`-style replace `group: wheel` → `group: "{{ 'wheel' if ansible_system == 'Darwin' else 'root' }}"` in all three files (9 occurrences total).

**H4 — node_exporter downloads have no checksum verification anywhere.**
`roles/node_exporter/tasks/{linux,macos}.yml:12-16` and the canonical `tasks/bootstrap/node_exporter_{linux,macos}.yml:28-31` all `get_url` the tarball with no `checksum:` parameter. Prometheus publishes `sha256sums.txt` alongside every release. Supply-chain risk: a compromised or corrupted download installs and runs unverified as root (roles/node_exporter) or as the `node_exporter` system user (canonical Linux path) with no integrity check, unlike the Salt install paths which all verify sha512 (`install_macos.yml:120-133`, `install_linux_onedir.yml:140-150`). Fix: add `checksum: "sha256:{{ node_exporter_sha256 }}"` to the `get_url` tasks, sourcing the hash from a `group_vars/all.yml` per-version map or fetching `sha256sums.txt` first.

**H5 — Hardcoded Tailscale IP `100.89.50.27` repeated in three live files.**
`install_salt_master.yml:127`, `install_salt_master_linux.yml:105`, `setup_salt_master.yml:56` (the latter is being deleted per §2.1, so effectively two live occurrences remain after cleanup). `kri_ingest_base_url: "http://100.89.50.27/api/v1/ingest"` is set as a play-level `vars:` default in each file rather than sourced from `group_vars/all.yml`. If the kri server's Tailscale IP ever changes, both live files need a manual edit. Fix: move to `group_vars/all.yml: kri_ingest_base_url` and remove the per-playbook override (each playbook can still `-e` override it).

### Medium severity

**M1 — `shell`/`command` used where a module exists (idempotency + portability).**
- `bootstrap_node.yml:347-408` — `sw_vers`, `sysctl hw.logicalcpu`, `python3 -c ... hw.memsize`, `sysctl hw.model`/`system_profiler` are all collected via `shell`, duplicating facts `setup: gather_subset: ['min','hardware']` (already called at `bootstrap_node.yml:43-44`) provides natively: `ansible_memtotal_mb`, `ansible_processor_vcpus`, `ansible_product_name`. The macOS-specific bits (`sw_vers`, serial number) genuinely need shell since Ansible's `setup` module doesn't expose them on Darwin, but CPU count and RAM are redundant re-collection.
- `redeploy_kri.yml:50` — `command: cat "{{ kri_deploy_path }}/VERSION"` should be `ansible.builtin.slurp` (no shell dependency, structured output) or at minimum add `changed_when: false` (currently missing — every run of this task reports "changed").
- `tasks/bootstrap/node_deps.yml:78,103` — `brew install macmon`/`brew install cirruslabs/cli/tart` via raw `shell` instead of `community.general.homebrew` (would need vendoring that collection — see prior plan's open question #2; until then, the current `changed_when: "'already installed' not in *_install.stderr"` pattern at lines 80, 105 is a reasonable manual approximation and does not need to block on the collection decision).

**M2 — Fragile shell pipelines without `pipefail`.**
- `bootstrap_node.yml:311` — `ps aux | grep -v grep | grep salt-minion` as the minion-running check. No `set -o pipefail`; if `ps` fails the pipeline still "succeeds" on the final `grep`'s exit code. A `command: pgrep -f salt-minion` (or `service_facts:`) would be simpler and correct.
- `tasks/bootstrap/node_exporter_linux.yml:22` / `node_exporter_macos.yml:22` — `node_exporter --version 2>&1 | head -1 | awk '{print $3}'` has the same class of issue; low risk since `failed_when: false` already tolerates the binary being absent, but a genuinely corrupted binary that exits nonzero mid-pipe with partial output could produce a wrong version string that's silently treated as "up to date."

**M3 — Missing `changed_when` causing always-`changed` reports.**
- `redeploy_kri.yml:23-27` (`git pull --ff-only`) and `:33-37` (`docker compose up -d --build`) have no `changed_when` — every run reports "changed" regardless of whether anything actually changed. Fix: key `git pull` on `"Already up to date." not in git_result.stdout`; key `docker compose` on absence of "up-to-date"/"Recreating" markers in `compose_result.stdout`.
- `bootstrap_node.yml:128` — `changed_when: clt_install.rc == 0` on the Xcode CLT install is effectively always-true when the shell block runs (the script always exits 0 whether or not it actually installed anything); low-impact since this task only runs at all `when: xcode_check.rc != 0`, i.e., once per node lifetime.

**M4 — Repeated grains-push blocks (see §2.4).** One task with an OS-conditional `body:` dict would remove ~35 lines of duplication (`bootstrap_node.yml:452-524`).

**M5 — Repeated check-then-install pairs not using loops.**
`tasks/bootstrap/node_deps.yml:65-113` — macmon and tart each get an independent check+install task pair (4 tasks, ~50 lines) that are structurally identical except for the package name and one string ("macmon" vs "cirruslabs/cli/tart"). Collapse into a single `loop: [{name: macmon, formula: macmon}, {name: tart, formula: cirruslabs/cli/tart}]` pair (2 tasks).

**M6 — Two independent `nc` reachability loops with fragile index-correlation.**
`bootstrap_node.yml:61-91` — checks port 4505 and port 4506 in two separate `loop: "{{ salt_masters }}"` shell tasks (lines 62-67, 70-75), then correlates them by `nc_4506_results.results[nc_4505_results.results.index(item)]` (line 82) inside a third loop. This is a fragile index-matching pattern (`.index(item)` on a Jinja dict comparison) that would misbehave if `salt_masters` ever contains duplicate entries. A single loop over `salt_masters | product([4505, 4506])` with one `wait_for:` task (no external `nc` binary dependency, which may be absent on minimal Linux images) would be simpler and more robust.

**M7 — `install_linux_onedir.yml` uses `local_action:` (deprecated form) while `pki.yml` in the same role already uses the modern `delegate_to: localhost`.**
`install_linux_onedir.yml:65,102`. `install_macos.yml:57,94` (referenced in the prior plan) also uses `local_action:`. Convert both to `delegate_to: localhost` for consistency with the rest of the role and to drop a deprecated construct.

### Low severity / hygiene

**L1 — FQCN inconsistency.** `roles/salt_master/handlers/main.yml` correctly uses `ansible.builtin.systemd` (lines 41, 50, 60, 69), but nearly every task file in the same role uses bare module names (`file`, `copy`, `template`, `get_url`, `shell`, `command`, `set_fact`, `uri`, `stat`, `slurp`, `unarchive`, `wait_for`, `group`, `user`, `apt`, `dnf`, `systemd`). `ansible-lint --fix` with the `fqcn` rule handles this mechanically.

**L2 — No `meta/main.yml` in either role.** Neither `roles/salt_master/` nor `roles/node_exporter/` has a `meta/main.yml`. Galaxy hygiene / `ansible-lint`'s `meta-no-dependencies` rule wants at minimum an empty `dependencies: []`.

**L3 — `validate_certs: false` on Artifactory downloads.** `install_macos.yml:45`, `install_linux_onedir.yml:53`. Same instance noted in the prior plan; still present, undocumented justification.

**L4 — Non-deterministic UID generation.** `api_user.yml:16` — `UniqueID "$(( 800 + RANDOM % 100 ))"` inside the macOS `dscl` fallback branch can produce a different, potentially colliding UID on every run where the fallback path executes (the primary `sysadminctl -addUser` path doesn't have this issue). Low likelihood of triggering (only hit when `sysadminctl` fails) but worth a fixed UID or an `id -u` pre-check loop.

**L5 — `install_macos.yml` header comment says "tasks/install.yml"** (`install_macos.yml:2`) — stale/misleading filename reference left over from a prior rename; purely cosmetic, one-line fix.

**L6 — `roles/salt_master/tasks/install_linux_onedir.yml` explicitly marked unvalidated in production** (lines 23-28, "LIVE-ENVIRONMENT VALIDATION NEEDED before first production use"). Not a bug, but should be tracked as an open item — this path is reachable today (`salt_linux_airgap: true` extravar) without having been smoke-tested per its own comment.

---

## 5. Prioritized action plan

| # | Change | Why | Effort | Risk | Filename-safety |
|---|---|---|---|---|---|
| 1 | Fix `group: wheel` hardcoding in `pki.yml`, `pillar.yml`, `states.yml` (H3) | Currently blocks every Linux salt-master install at the first PKI task | S | Low — copy the exact conditional already proven in `configure.yml` | No filenames touched |
| 2 | Delete `roles/node_exporter/tasks/{linux,macos}.yml` `meta: end_play`; replace bodies with canonical `tasks/bootstrap/node_exporter_*.yml` logic (H1, §2.2) | Multi-host `deploy_node_exporter.yml` run silently skips hosts today; also fixes the variable-scheme drift | M | Low — `deploy_node_exporter.yml`'s filename/`roles:` interface unchanged | None — role body only |
| 3 | Delete `deploy_salt_master_mm1.yml` and `setup_salt_master.yml` (§0, §2.1) | Confirmed zero call sites; risky hardcoded default password in the former | S | Very low | None — no code references either filename |
| 4 | Delete `group_vars/home.yml` and `inventory/dynamic.py` (§2.6) | Confirmed orphaned/dead | S | None | None |
| 5 | Remove forced restarts in `service_systemd.yml` / `service_macos.yml` (H2) | Every master-provisioning re-apply currently restarts salt-master + salt-api unnecessarily | S | Low — handlers already correctly wired via `notify:` elsewhere in the role | None |
| 6 | Add sha256 checksum to node_exporter downloads (H4) | Supply-chain gap; Salt paths already do this, node_exporter doesn't | S | Low | None |
| 7 | Extract `kri_ingest_base_url` to `group_vars/all.yml` (H5) | Two live playbooks hardcode the same Tailscale IP | S | Low | None |
| 8 | Merge `install_salt_master.yml` / `install_salt_master_linux.yml` into one OS-conditional playbook | Removes the last real "4 wrapper" duplication, per both prior docs | M | Medium — must update `ansible_tasks.py:688-691` (`_MASTER_PLAYBOOKS`) and `scripts/kri:847,860` in the same PR, not just the playbook (§0 correction) | Code-level, not filename-shim — the risk is a missed call site, not a saved-job break |
| 9 | Collapse duplicated grains-push blocks (§2.4, M4) | ~35 lines of duplication in the bootstrap monolith | S | Low | None |
| 10 | Fix `bootstrap_node.yml` reachability double-loop (M6) | Fragile `.index(item)` correlation; `nc` binary dependency | M | Low | None |
| 11 | Extract shared salt apt/yum repo-setup into one task file, used by both `tasks/bootstrap/minion_linux.yml` and `roles/salt_master/tasks/install_{debian,redhat}.yml` (§2.5) | Two sources of truth for the same repo-add logic | M | Medium — touches the live bootstrap path; needs a real macOS+Linux bootstrap test before merge | None |
| 12 | Full `salt_minion` role extraction + thin `bootstrap_node.yml` (per both prior docs, Phase 3 of the plan) | The 534-line monolith is the largest structural risk in the tree | L | High — touches the live, sole bootstrap entry point | Same filename kept; extravars contract must not change |
| 13 | FQCN pass, `meta/main.yml` for both roles, ansible-lint CI gate | Hygiene, catches future regressions of this exact class (H3 is proof the lack of lint let a fix regress) | L | Low | None |

---

## 6. Quick wins (< 30 minutes each)

**QW-1 — Fix `group: wheel` in 3 files (H3).** Copy the exact Jinja conditional already in `configure.yml:9` into `pki.yml:11,73,82,91`, `pillar.yml:10,24,40,52`, `states.yml:9,21`. This is the single highest-value quick win — it currently hard-blocks every Linux master install.

**QW-2 — Delete `deploy_salt_master_mm1.yml` and `setup_salt_master.yml`.** Confirmed zero call sites (§0). No shim required.

**QW-3 — Delete `group_vars/home.yml` and `inventory/dynamic.py`.** Confirmed orphaned (§0, §2.6).

**QW-4 — Remove the unconditional `launchctl load/start` block in `service_macos.yml:24-53`; remove `state: restarted` from `service_systemd.yml:7,15` in favor of `state: started, enabled: true`.** Handlers already fire correctly on config change via `notify:` elsewhere in the role — this just stops the redundant forced restart on every no-op re-apply.

**QW-5 — Add `changed_when` to `redeploy_kri.yml`'s `git pull` (line 23) and `cat VERSION` (line 50) tasks.** `git pull`: `changed_when: "'Already up to date.' not in git_result.stdout"`. `cat VERSION`: `changed_when: false` (read-only).

---

## Summary of corrections to prior docs

- **`docs/ANSIBLE_REVIEW.md`**: Gaps 1, 2, 4, 8 are fixed in the current tree — mark resolved, don't re-open. Gap 13 (`meta: end_play`) is still open and is the single biggest live bug found in this audit. New finding not in that doc: the wheel-group fix in Gap 8 wasn't propagated to `pki.yml`/`pillar.yml`/`states.yml` (now H3 above) — a regression-class bug the lack of `ansible-lint` in CI (that doc's Gap 11) would have caught.
- **`docs/superpowers/specs/2026-06-26-ansible-role-consolidation-design.md`** and **`docs/superpowers/plans/2026-07-05-ansible-roles-refactor-plan.md`**: both correctly identify the node_exporter drift (§2.2, confirmed and extended here with live-extravars proof) and the shared download/checksum/extract pattern (§2.6). Both **understate** that two of the four "salt-master wrapper playbooks" are live, OS-dispatched, code-level dependencies (`_MASTER_PLAYBOOKS`) while the other two are simply dead — the "keep as shims" mitigation they propose for filename safety is unnecessary for the two dead files (delete outright) and insufficient by itself for the two live files (a code change in `ansible_tasks.py` + `scripts/kri` is required regardless of whether a shim exists). This report's §0/§2.1 should be read as the authoritative correction before executing Phase 4 of the 2026-07-05 plan.
