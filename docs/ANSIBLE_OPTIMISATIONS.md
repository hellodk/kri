# Ansible Playbooks — Optimisation Analysis

## Current State Summary

| Component | Files | Lines |
|-----------|-------|-------|
| **Playbooks** (7) | `bootstrap_node`, `deploy_salt_master_mm1`, `install_salt_master`, `install_salt_master_linux`, `reconfigure_minion_masters`, `redeploy_kri`, `setup_salt_master` | ~614 |
| **Tasks** (2) | `host_prep`, `host_prep_gate` | ~132 |
| **Roles** (7) | `common`, `salt_master`, `salt_minion`, `node_exporter`, `node_telemetry`, `otel_collector`, `kri_enroll` | ~1,200+ |
| **group_vars/all.yml** | Central defaults | 67 |
| **host_vars/mm1.yml** | mm1 overrides | 6 |

---

## Issues Found

### 1. Duplicate Playbooks — Do the Same Job

**`setup_salt_master.yml`** and **`deploy_salt_master_mm1.yml`** are functionally identical: both install `salt_master` role on mm1. The only difference is `setup_salt_master.yml` pre-exports pillar from Docker. `deploy_salt_master_mm1.yml` skips that.

**`install_salt_master.yml`** (macOS) and **`install_salt_master_linux.yml`** (Linux) are 90% identical. Both do:
- Pre-flight validation of `target_host`
- Check for bundled installer (airgap check)
- Apply `salt_master` role
- Print post-install instructions

The only real differences are: macOS checks `.pkg` vs Linux checks `.tar.xz`, and Linux has an extra `gather_facts: true`.

**→ Consolidate to 2 playbooks:** `deploy_salt_master.yml` (replaces `setup_salt_master.yml` + `deploy_salt_master_mm1.yml` + `install_salt_master.yml` + `install_salt_master_linux.yml`) with OS detection in a single pre-flight play.

### 2. Repeated SSH/Become Vars Across Every Playbook

Every playbook that targets `targets` or `fleet` repeats the same boilerplate:
```yaml
vars:
  ansible_ssh_common_args: '-o StrictHostKeyChecking=no ...'
  ansible_become: true
  ansible_become_method: sudo
```

This already exists in `ansible.cfg` under `[ssh_connection]`, but playbooks override it per-play. **→ Move into `group_vars/all.yml`** or a `playbooks/group_vars/targets.yml` and delete the per-playbook declarations.

### 3. `salt_master` Role Rederives Facts `common` Already Sets

`salt_master/tasks/main.yml:29-41` runs `shell: uname -m` to get CPU arch, even though `common` already sets `cpu_arch` from gathered facts. The role even has `setup:` with `gather_subset` to handle the case where facts weren't gathered. **→ Depend on `common` via `meta/main.yml`** and drop the `uname -m` shell call.

### 4. `salt_master/tasks/configure.yml` Repeats `group: wheel/root` 5 Times

```yaml
group: "{{ 'wheel' if ansible_system == 'Darwin' else 'root' }}"
```

Appears in `configure.yml` (x4), `pki.yml` (x6), `pillar.yml` (x5), `states.yml` (x2), `api_user.yml` (x2), `api_tls.yml` (x2), `minion.yml` (x3) — ~24 repetitions across the role. **→ Define `salt_group` in `salt_master/defaults/main.yml`** (already done in `common` role but `salt_master` doesn't use it).

### 5. Checksum Verification Copy-Pasted 5 Times

The exact same checksum verification shell block appears in:
- `salt_master/tasks/install_macos.yml:52-65`
- `salt_master/tasks/install_linux_onedir.yml:56-68`
- `salt_minion/tasks/install_macos.yml:50-61`
- `salt_minion/tasks/install_linux_onedir.yml:64-77`
- `node_exporter/tasks/install.yml:38-52`

**→ Extract to `playbooks/tasks/verify_checksum.yml`** as a reusable task file with `archive`, `checksum_file` params.

### 6. Onedir Install Logic Duplicated Between `salt_master` and `salt_minion`

`salt_master/tasks/install_linux_onedir.yml` (118 lines) and `salt_minion/tasks/install_linux_onedir.yml` (151 lines) are nearly identical: copy tarball, verify checksum, extract, create symlinks, write systemd unit, verify version. The only differences are which binaries get symlinked and which binary is used for version verification.

**→ Extract a shared `playbooks/tasks/install_onedir.yml`** parameterized by `onedir_symlinks` and `onedir_version_bin`.

### 7. `node_exporter` and `otel_collector` Re-derive OS/Arch Facts

Both roles independently do:
```yaml
- name: Set OS/arch facts
  set_fact:
    ne_os: "linux"
    ne_arch: "{{ 'arm64' if ansible_architecture in [...] else 'amd64' }}"
```

`otel_collector` does the same with `otel_os` / `otel_arch`. The `common` role already sets `ne_os`, `ne_arch`, `cpu_arch`. **→ Have both roles `import_role: common` in `meta/main.yml`** and use the already-set facts. This removes ~12 lines of duplication.

### 8. Hardcoded `artifactory_binary_url` in `salt_master` Defaults

`salt_master/defaults/main.yml:8`:
```yaml
artifactory_binary_url: "http://10.105.205.92:8082/artifactory/example-repo-local/salt"
```

This is a hardcoded internal IP that conflicts with `group_vars/all.yml:25` where it's set to `""`. Since role defaults have lowest precedence, `group_vars/all.yml` wins — but the hardcoded value is confusing and suggests a stale copy. **→ Set to `""` in role defaults to match group_vars.**

### 9. Missing `meta/main.yml` in `salt_master`

`salt_master` has no `meta/main.yml`, so there's no declared dependency on `common`. Other roles (`node_exporter`, `otel_collector`) also lack it. **→ Add `meta/main.yml` to all roles** declaring dependencies.

### 10. `redeploy_kri.yml` Uses `command` Instead of `ansible.builtin.git`

`redeploy_kri.yml:24` uses `command: git pull --ff-only` instead of `ansible.builtin.git`. The `git` module is idempotent and handles fetch/pull cleanly. Same for `command: docker compose up` at line 34 — **→ Use `community.docker.docker_compose_v2`** or at minimum `changed_when` to track actual changes.

---

## Recommended New Structure

```
playbooks/
├── ansible.cfg                          # keep as-is
├── requirements.yml                     # keep as-is
│
├── deploy_salt_master.yml               # NEW — replaces 4 playbooks
│                                         # Single playbook with 2 plays:
│   # play 1: pre-flight localhost (validate target_host, detect OS)
│   # play 2: install salt-master on target
│
├── bootstrap_node.yml                   # keep (already well-structured)
├── reconfigure_minion_masters.yml       # keep (already clean)
├── redeploy_kri.yml                     # minor fixes
│
├── group_vars/
│   ├── all.yml                          # add SSH/become defaults here
│   └── targets.yml                      # NEW — SSH args for target group
│
├── tasks/
│   ├── host_prep.yml                    # keep
│   ├── host_prep_gate.yml               # keep
│   ├── verify_checksum.yml              # NEW — reusable checksum task
│   └── install_onedir.yml               # NEW — shared onedir install
│
├── roles/
│   ├── common/meta/main.yml             # add dependency declarations
│   ├── salt_master/
│   │   ├── meta/main.yml               # NEW — depends on common
│   │   ├── defaults/main.yml            # fix artifactory_binary_url to ""
│   │   └── tasks/
│   │       ├── main.yml                 # drop uname -m, use common facts
│   │       ├── configure.yml            # use salt_group var
│   │       └── install_linux_onedir.yml # use shared tasks/install_onedir.yml
│   ├── salt_minion/
│   │   ├── meta/main.yml               # NEW — depends on common
│   │   └── tasks/install_linux_onedir.yml # use shared tasks/install_onedir.yml
│   ├── node_exporter/meta/main.yml      # NEW — depends on common
│   ├── otel_collector/meta/main.yml     # NEW — depends on common
│   └── ...
```

### Lines Saved (Estimated)

| Change | Lines Removed |
|--------|---------------|
| Merge 4 salt-master playbooks → 1 | ~250 |
| Drop per-playbook SSH/become vars | ~30 |
| Shared `salt_group` variable | ~24 repetitions → 0 |
| Extract checksum verification | ~40 (5 copies → 1) |
| Extract onedir install | ~100 (2 copies → 1) |
| Drop `uname -m` in salt_master | ~8 |
| Remove duplicate OS/arch fact-setting in node_exporter + otel_collector | ~12 |
| **Total** | **~464 lines** |

The remaining playbooks (`bootstrap_node`, `reconfigure_minion_masters`, `redeploy_kri`) are already well-structured thin orchestrators — no further consolidation needed there.

### What NOT to Change

- `bootstrap_node.yml` — already uses a clean 2-play architecture (monitoring decoupled from Salt per #967)
- `reconfigure_minion_masters.yml` — already thin, imports role tasks via `tasks_from`
- `kri_enroll` role — clean and focused
- `node_telemetry` role — well-structured
- Handlers — already handle macOS/Linux split cleanly
- Templates — all properly parameterized
