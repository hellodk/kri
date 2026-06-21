# Ansible Setup Review — kri Fleet Platform

**Scope:** `playbooks/roles/salt_master/`, `playbooks/roles/node_exporter/`, all top-level playbooks, `ansible.cfg`, `group_vars/`, `host_vars/`, `inventory/`.
**Reviewer position:** senior DevOps, read-only analysis.

---

## 1. Current Strengths

### Role structure and OS-family dispatch
`tasks/main.yml` cleanly gates every OS-specific branch via `_salt_os` before doing any work, fails fast with a human-readable message on unsupported platforms, and uses `include_tasks`/`import_tasks` correctly — dynamic includes for install/service (need the OS gate), static imports for shared tasks (configure, pki, pillar, states, verify). The hierarchy is easy to follow.

### macOS install: three-tier download fallback
`install_macos.yml` tries Artifactory first, falls back to a local bundle on the controller, then falls back to the official URL, verifying a sha512 checksum before copying to the target. The pkg install itself is gated by `pkgutil --pkg-info` (not `salt-master --version`, which would hang on macOS onedir). The controller-side download + SSH copy design means the target node never needs internet access. This is well thought-out.

### Idempotency on critical paths
- `pkgutil` version gate prevents re-installing an already-correct Salt version.
- `command: openssl req ... args: creates:` in `api_tls.yml` ensures TLS cert is generated exactly once.
- `template` + `notify` in `configure.yml` fires handler restarts only when config changes.
- `api_user.yml` wraps `sysadminctl`/`dscl` in an `id` check and correctly sets `changed_when: "'created' in api_user_result.stdout"`.

### PKI stability strategy
`pki.yml` uses `slurp` (not `copy: src`) to read the controller-side master keypair, avoids the `become`-vs-file-ownership problem documented in the inline comment, and gracefully skips if no pre-provisioned keys exist — letting salt-master self-generate on first boot. The `stat: follow: true` on the symlink is correct.

### Least-privilege salt-api ACL
`kri-master.conf.j2` scopes `external_auth` to an explicit function allowlist (no `.*` or bare `@wheel`) and explicitly enables only the four `netapi_enable_clients` that kri uses. The comment noting that the list must stay in sync with `_DEFAULT_SALT_FUNCTIONS` in `platform_settings_svc.py` is exactly the right cross-reference.

### End-to-end verification
`verify.yml` goes beyond a port check: it performs a real `POST /login` eauth probe that would catch misconfigured PAM, wrong password, or broken `external_auth` ACL. This is a meaningful integration smoke test, not security theater.

### Minion-vantage reachability gate
`bootstrap_mac_mini.yml` checks TCP reachability to each salt-master on 4505/4506 from the node itself before writing any config. This surfaces network/firewall issues before the minion wastes time trying to connect to an unreachable master.

### Pre-flight checks in playbooks
`install_salt_master.yml` validates `target_host` and the local pkg file before touching the remote host. This catches the most common operator errors before any SSH connections are made.

### `no_log: true` on sensitive tasks
`api_user.yml` and the grains push in `bootstrap_mac_mini.yml` both set `no_log: true` where passwords and tokens appear in task arguments. This is correct.

### `ansible.cfg` discipline
`task_timeout = 300`, `retries = 2`, `pipelining = True`, and `forks = 20` are all reasonable production defaults. Disabling `host_key_checking` globally is appropriate for a dynamically-managed Mac Mini fleet (though see Gap 4).

---

## 2. Gaps & Risks

### Gap 1 — `api_user.yml` is macOS-only; Linux gets no service account
**File:** `tasks/api_user.yml` (entire file)

The PAM user creation uses `sysadminctl` + `dscl`, both macOS-only tools. When the role runs on Debian/RHEL via `install_salt_master_linux.yml`, `api_user.yml` is still unconditionally imported (`main.yml:50`). On Linux these commands will either fail or be silently absent, meaning `salt-api` PAM auth will break.

There is no `when: _salt_os == 'macos'` guard on the `import_tasks: api_user.yml` line. Linux needs `useradd`/`passwd` or `user:` module equivalents.

**Main.yml line 50:**
```yaml
- import_tasks: api_user.yml    # ← runs on Linux with no Linux user-creation logic
```

### Gap 2 — Linux install does not install `salt-api`
**Files:** `tasks/install_debian.yml:24`, `tasks/install_redhat.yml:14`

Both Linux installers install only `salt-master`, not `salt-api`. The `service_systemd.yml:11` task handles this with `failed_when: false`, which silently swallows the systemd "unit not found" error and reports `ok`. The service never actually starts.

```yaml
# install_debian.yml:24
- name: Install salt-master
  apt:
    name: "salt-master={{ salt_version }}*"   # ← no salt-api package

# service_systemd.yml:11
- name: Enable and start salt-api (if installed)
  systemd:
    name: salt-api
    ...
  failed_when: false    # ← silently succeeds even when salt-api is absent
```

On a Linux salt-master kri will have no HTTP API to talk to.

### Gap 3 — Air-gap asymmetry: macOS bundles the pkg; Linux fetches from the internet
**Files:** `tasks/install_debian.yml:13-18`, `tasks/install_redhat.yml:5-10`

Linux installs fetch the repo key and package from `packages.broadcom.com` at runtime. The macOS install goes to great lengths to support Artifactory and local bundle fallback to avoid internet access on the target. Linux has no equivalent. In an air-gapped or restricted-egress environment, Linux installs will silently fail at the `get_url` / `apt` step with a connectivity error.

### Gap 4 — `handlers/main.yml` handlers are macOS-only
**File:** `handlers/main.yml` (entire file)

All four handlers (`Restart salt-master`, `Reload and start salt-master`, `Restart salt-api`, `Reload and start salt-api`) use `launchctl`. They are notified by `configure.yml` (which runs on all OSes). On Linux, notifying these handlers would either error or — if the handler name matches something unexpected — produce incorrect behaviour. `service_systemd.yml` hard-restarts services unconditionally without handlers, but template changes on a running Linux master will notify macOS-only handlers.

### Gap 5 — `service_macos.yml` unconditionally calls `launchctl load/start` regardless of change
**File:** `tasks/service_macos.yml:24-55`

The service load/start tasks always run (`changed_when: false`) regardless of whether the plist actually changed. This means every playbook run restarts both services on macOS — undermining idempotency and causing unnecessary service interruptions. The plist writes correctly use `notify` handlers; the unconditional `launchctl load` block below them is redundant and harmful.

### Gap 6 — `failed_when: false` masks real failures
Several tasks use `failed_when: false` where silent failure causes downstream breakage:

| File | Line | Issue |
|------|------|-------|
| `tasks/install_macos.yml:27` | `failed_when: false` on pkgutil check | Benign (version detect) |
| `tasks/service_systemd.yml:17` | `failed_when: false` on salt-api systemd | Silently skips salt-api — see Gap 2 |
| `tasks/service_macos.yml:67` | `failed_when: false` on `salt-key -L` | Salt not running would go undetected |
| `tasks/pillar.yml:56` | `failed_when: false` on pillar sync copy | Silently skips pillar migration |
| `playbooks/bootstrap_mac_mini.yml:394-414` | `failed_when: false` on heartbeat/process-report apply | Schedule never set, node goes offline |

The pillar and bootstrap heartbeat cases are operational risks: a failed pillar sync means the new master has no per-node tokens; a failed heartbeat schedule means nodes go offline after ~15 minutes with no indication during bootstrap that this happened.

### Gap 7 — `bootstrap_mac_mini.yml` calls `salt-minion --version` for version detection
**File:** `playbooks/bootstrap_mac_mini.yml:143`

```yaml
- name: Check installed salt version
  shell: /opt/salt/salt-minion --version 2>/dev/null | awk '{print $2}'
```

The `install_macos.yml` correctly avoids `--version` because the onedir salt-master binary boots the daemon and never exits. The bootstrap playbook uses `salt-minion --version`, which does the same thing for the minion binary. This will hang until `task_timeout` (300s). The fix used in the role (`pkgutil --pkg-info`) should be used here too.

**Note:** This bug exists in the bootstrap playbook, not the role. The role correctly uses pkgutil.

### Gap 8 — `configure.yml` hardcodes `group: wheel` on all OSes
**File:** `tasks/configure.yml:8,14`

```yaml
group: wheel   # line 8 and 14
```

`wheel` is the correct group on macOS but does not exist on most Linux distros (default group for root-owned files is `root`). `api_tls.yml` correctly conditionalises this (`'wheel' if ansible_system == 'Darwin' else 'root'`), but `configure.yml` does not. On Debian/RHEL, the `file:` task for `/etc/salt` and `/etc/salt/master.d` will fail because the `wheel` group does not exist.

### Gap 9 — `bootstrap_mac_mini.yml` has duplicate / dead download logic
**File:** `playbooks/bootstrap_mac_mini.yml:149-183`

There are three tasks that attempt to download the salt pkg:
1. Download checksum (line 149) then read it via `lookup('file', '/tmp/...')` which runs on the controller, not the remote host.
2. Download pkg with a checksum built from that local lookup (line 158) — this can only work if `/tmp/...` exists on the controller, not the target. This will silently fail.
3. A second unconditional `get_url` for the pkg (line 178) with no checksum.

The `vars: _checksum_raw: "{{ lookup('pipe', ...) }}"` on line 170 uses `lookup('pipe', 'cat /tmp/...')` which runs on the controller but the file is on the target. The net effect is that the integrity check in step 2 will silently not run, and step 3 will download the pkg without verifying checksum. The subsequent `shell: shasum` task (line 186) does perform a real check, but only after an unverified download.

### Gap 10 — Tailscale IP hardcoded in two playbooks
**Files:** `playbooks/install_salt_master.yml:127`, `playbooks/install_salt_master_linux.yml:76`, `playbooks/setup_salt_master.yml:56`

```yaml
kri_ingest_base_url: "http://100.89.50.27/api/v1/ingest"
```

This Tailscale IP is hardcoded in three playbooks (and also in `deploy_salt_master_mm1.yml:49` output text). If the kri server IP changes, these must all be updated manually. This should be a single `group_vars/all.yml` variable.

### Gap 11 — No Molecule tests, no ansible-lint CI
There is no `molecule/` directory in the role, no `.ansible-lint` config, and no CI step that runs `ansible-lint` or `ansible-playbook --check` against the role. Regressions in any task file are caught only when someone runs the playbook against a real host. The `install_macos.yml` and `bootstrap_mac_mini.yml` code drift is evidence of this — the same pattern (pkgutil vs `--version`) diverged without a test to catch it.

### Gap 12 — `node_exporter` role hardcodes `linux-amd64` architecture
**File:** `roles/node_exporter/tasks/linux.yml:13`

```yaml
url: ".../node_exporter-{{ node_exporter_version }}.linux-amd64.tar.gz"
```

The macOS task correctly conditionalises on `darwin-arm64`; the Linux task hardcodes `amd64`. A fleet node with a Linux arm64 host (e.g., Raspberry Pi, AWS Graviton) would download the wrong binary.

### Gap 13 — `node_exporter` role uses `meta: end_play` for idempotency
**File:** `roles/node_exporter/tasks/macos.yml:9`

```yaml
- name: Skip if already running
  meta: end_play
  when: port_check.rc == 0 and port_check.stdout != ""
```

`meta: end_play` aborts the entire play, not just this role. In a playbook that includes other roles after `node_exporter`, those roles will never run when node_exporter is already present. The correct idiom is `block:` + `when:` conditions or a proper `creates:` guard on the binary copy.

### Gap 14 — `host_vars/mm1.yml` stores `ansible_become_password` in cleartext
**File:** `playbooks/host_vars/mm1.yml:3`

```yaml
ansible_become_password: '{{ ansible_ssh_pass }}'
```

`ansible_ssh_pass` is itself expected to come from somewhere (likely `-e` or an Ansible vault). If the operator sets it via `-e ansible_ssh_pass=<password>` on the command line, it will appear in bash history. This should be documented as requiring `--ask-become-pass` or vault, not passed as a plain extra var.

---

## 3. Prioritized Recommendations

| # | Improvement | Why It Matters | Effort | Suggested Issue |
|---|-------------|---------------|--------|-----------------|
| 1 | Add `when: _salt_os == 'macos'` guard on `import_tasks: api_user.yml`; add Linux `user:` task | Linux salt-api PAM auth is broken without it | S | `fix: api_user.yml Linux support` |
| 2 | Add `salt-api` to both `install_debian.yml` and `install_redhat.yml`; remove `failed_when: false` from `service_systemd.yml` salt-api task | kri has no HTTP API on Linux masters | S | `fix: install salt-api on Linux` |
| 3 | Fix `group: wheel` → conditional in `configure.yml` | `/etc/salt` dir creation fails on Linux | S | `fix: salt dir group on Linux` |
| 4 | Fix handlers to be OS-conditional (or add Linux `systemd` handler variants) | Template changes on Linux notify macOS-only launchctl handlers | M | `fix: cross-platform handlers` |
| 5 | Remove the unconditional `launchctl load/start` block in `service_macos.yml`; rely solely on handlers | Every run restarts salt services unnecessarily | S | `fix: service_macos idempotency` |
| 6 | Add Linux air-gap download support (local pkg copy path) matching macOS install | Linux installs break in air-gapped or internet-restricted environments | M | `feat: Linux air-gap salt install` |
| 7 | Replace `salt-minion --version` with `pkgutil` in `bootstrap_mac_mini.yml:143` | 300s hang on every bootstrap where minion already installed | S | `fix: bootstrap version detect hang` |
| 8 | Fix bootstrap checksum logic (slurp on remote, not lookup on controller) | Integrity check silently skipped for minion pkg | M | `fix: bootstrap pkg checksum` |
| 9 | Change `failed_when: false` on pillar sync and heartbeat apply to `ignore_errors: true` + explicit warning | Silent failures mean missing pillar data and nodes going offline | S | `fix: surface bootstrap failures` |
| 10 | Extract hardcoded Tailscale IP to `group_vars/all.yml: kri_server_ip` | Three-point update risk when kri server IP changes | S | `chore: remove hardcoded kri IP` |
| 11 | Replace `meta: end_play` with `block:` + `when:` in `node_exporter` role | Aborts entire play when node_exporter already installed | S | `fix: node_exporter end_play` |
| 12 | Add `ansible-lint` to CI (or a pre-commit hook); add Molecule test scenario for Linux | Catches the class of bugs already present: wrong group, missing packages, OS-blindspot | L | `chore: ansible lint + molecule` |
| 13 | Conditionalise `node_exporter` Linux download URL on `ansible_architecture` | Wrong binary downloaded on arm64 Linux | S | `fix: node_exporter linux arch` |

---

## 4. Quick Wins (< 30 minutes each)

**QW-1 — Guard `api_user.yml` on macOS** (`tasks/main.yml:50`)
```yaml
# Change:
- import_tasks: api_user.yml
# To:
- import_tasks: api_user.yml
  when: _salt_os == 'macos'
```
Prevents the task from running on Linux and surfacing misleading errors. The Linux equivalent is a separate `user:` task (takes 10 min to add).

**QW-2 — Fix `configure.yml` group to be OS-conditional** (`tasks/configure.yml:8,14`)
```yaml
group: "{{ 'wheel' if ansible_system == 'Darwin' else 'root' }}"
```
Identical to the pattern already used in `api_tls.yml`. Copy-paste from there.

**QW-3 — Add `salt-api` to the Debian installer** (`tasks/install_debian.yml:24`)
```yaml
- name: Install salt-master and salt-api
  apt:
    name:
      - "salt-master={{ salt_version }}*"
      - "salt-api={{ salt_version }}*"
    update_cache: true
    state: present
  become: true
```
Same change for `install_redhat.yml` (add `salt-api-{{ salt_version }}` to the dnf task).

**QW-4 — Remove unconditional launchctl restart in `service_macos.yml`**
Delete lines 24–35 (the `Load salt-master` and `Start salt-master` shell tasks with `changed_when: false`). The `Reload and start salt-master` handler, already notified by the plist template task, handles service activation. The unconditional block causes a restart on every run.

**QW-5 — Fix the version-detect hang in `bootstrap_mac_mini.yml:143`**
```yaml
# Change:
shell: /opt/salt/salt-minion --version 2>/dev/null | awk '{print $2}'
# To:
shell: pkgutil --pkg-info com.saltstack.salt 2>/dev/null | awk '/^version:/ {print $2}'
```
The fix is already present in `install_macos.yml:22` — copy it directly.

---

## Summary Table of File-Level Issues

| File | Issue |
|------|-------|
| `tasks/main.yml:50` | `api_user.yml` imported unconditionally — runs macOS commands on Linux |
| `tasks/configure.yml:8,14` | `group: wheel` hardcoded — fails on Linux |
| `tasks/handlers/main.yml` (all) | All handlers are macOS launchctl only — no Linux systemd handlers |
| `tasks/install_debian.yml:24` | Missing `salt-api` package |
| `tasks/install_redhat.yml:14` | Missing `salt-api` package |
| `tasks/install_debian.yml:13` | Fetches repo key from internet — no air-gap path |
| `tasks/service_macos.yml:24-35` | Unconditional `launchctl load/start` restarts services on every run |
| `tasks/service_systemd.yml:17` | `failed_when: false` silently hides missing salt-api |
| `tasks/pillar.yml:56` | `failed_when: false` silently skips pillar migration |
| `playbooks/bootstrap_mac_mini.yml:143` | `salt-minion --version` hangs on macOS onedir |
| `playbooks/bootstrap_mac_mini.yml:158-170` | Checksum lookup runs on controller for file on target |
| `playbooks/bootstrap_mac_mini.yml:394-414` | `failed_when: false` on heartbeat/process-report — silent schedule miss |
| `playbooks/install_salt_master.yml:127` | Hardcoded Tailscale IP |
| `playbooks/install_salt_master_linux.yml:76` | Hardcoded Tailscale IP |
| `playbooks/setup_salt_master.yml:56` | Hardcoded Tailscale IP |
| `roles/node_exporter/tasks/linux.yml:13` | Hardcoded `linux-amd64` — fails on arm64 Linux |
| `roles/node_exporter/tasks/macos.yml:9` | `meta: end_play` aborts entire play |
| `playbooks/host_vars/mm1.yml:3` | `ansible_become_password` in cleartext yaml |
