# Ansible Role Consolidation + Push-Telemetry Bootstrap — Design

- **Date:** 2026-06-26
- **Scope:** `kri/playbooks/` only (bootstrap, node_exporter, salt_master). Hydra's `ansible/` tree is out of scope except as the source of the telemetry pattern and prebuilt exporter binaries.
- **Status:** Design — pending user review before implementation planning.

## 1. Problem / motivation

`playbooks/` has accumulated redundancy, drift, and a monolith:

1. **node_exporter implemented twice and drifted.** `roles/node_exporter/` (hardcoded arch, no checksum, GitHub-only, runs as root, vars `node_exporter_port`/`node_exporter_install_dir`) vs `tasks/bootstrap/node_exporter_{linux,macos}.yml` (arch-aware, checksum + Artifactory + override, dedicated system user, var `node_exporter_listen_address`). Two sources of truth, two variable schemes.
2. **salt-master: four near-duplicate playbooks** wrapping one role — `setup_salt_master.yml`, `install_salt_master.yml` (macOS), `install_salt_master_linux.yml` (Linux), `deploy_salt_master_mm1.yml` — with the macOS/Linux split done as *separate playbooks*.
3. **No salt-minion role.** Minion install is ~200 lines inline in `bootstrap_node.yml` (macOS pkg) plus `tasks/bootstrap/minion_linux.yml`.
4. **`bootstrap_node.yml` is a 527-line monolith** mixing ~10 concerns inline.
5. **OS handled by separate task files** instead of conditionals; **duplicated tasks** (two grains-push `uri:` blocks, repeated brew check/install pairs, repeated download/checksum/extract patterns, repeated dir-creation).
6. **No push telemetry.** node_exporter is pull-only; there is no agent shipping metrics to a central collector, and the hydra hardware exporter is not installed by kri.

## 2. Goals

- Everything reusable becomes a **slim role**; OS differences handled with **idiomatic conditionals** (one `main.yml` → `include_tasks: install_{macos,debian,redhat}.yml` with `when:`), not separate playbooks/jobs.
- **Bootstrap installs:** salt-minion, node telemetry deps, the hydra hardware exporter, and a **push-based OTel agent**. node_exporter is optional (off by default).
- Collapse duplicate tasks using loops and shared task files.
- **Pre-bootstrap variable collection** (Web UI + CLI): mandatory salt-master address (from existing masters, or manual entry if none); telemetry collector endpoint (defaulted, overridable); optional node_exporter.
- **Completion notification:** print a config summary and email it (secrets masked) via kri's existing mailer, only to SMTP-configured recipients.
- Remove the redundant/drifted implementations.

### Non-goals

- Changing hydra's `ansible/` tree.
- Replacing Salt as the control plane.
- Building a new metrics backend — we push to an existing stack (Victoria Metrics / OTEL gateway) and/or kri.

## 3. Design decisions (resolved with stakeholder)

| # | Decision | Choice |
|---|---|---|
| Scope | Which tree | `kri/playbooks/` only |
| Prompt surface | UI vs CLI | **Both**: kri Web UI (extravars, canonical for the non-interactive worker) + an Ansible `vars_prompt` block for standalone CLI runs |
| Telemetry | Pull vs push | **Push**: per-node OTel Collector agent (`otelcol-contrib`) pushes OTLP + Prometheus remote_write to a central collector |
| Collector endpoint | Default | Push to the existing in-cluster **OTel gateway** via NodePort, default `100.89.50.27:30317` (OTLP/gRPC, Tailscale) — verified live 2026-06-26. **No Victoria Metrics** in this cluster, so the VM remote_write exporter is dropped. Always allow per-bootstrap override/prompt. |
| hw-exporter delivery | Binary source + selection | **Prebuilt binaries** for apple/nvidia/amd shipped in `playbooks/files/` (air-gap friendly; no Go/build on targets); the role **auto-detects** the accelerator and installs only the matching one |
| Email | Transport/recipients | Reuse **kri's existing mailer** (same path as harden-approval mail); send to the triggering user and/or a configurable ops list; **only** to addresses present in kri's SMTP/allowed-recipient config; secrets masked |
| OS split | Style | **Idiomatic** — per-OS `include_tasks` gated by `when:` inside each role |
| node_exporter | Role in bootstrap | **OTel hostmetrics is the universal OS-metrics source**; node_exporter is **optional, OFF by default** (enable per-node/group when `node_*` dashboards / textfile collector are needed) |
| Salt role shape | 1 vs N | **Two slim roles**: `salt_minion` and `salt_master` (salt-api is a **tagged sub-step of master**, not a peer). Bootstrap calls only `salt_minion`. |
| node_base | Role vs inline | **Inline** — bootstrap-only host-prep glue lives in the playbook (`tasks/host_prep.yml`), not a role |
| node_telemetry | Role vs inline | **Role** — plausibly reused for "repair node deps" re-runs |

### Rule applied for what earns a role

> A role is a **reusable, cohesive installer**. Bootstrap-only orchestration glue stays in the playbook.

By this rule `salt_minion`, `salt_master`, `otel_agent`, `hw_exporter`, `node_exporter`, `node_telemetry` are roles (reused by other playbooks). Xcode CLT, authorized_keys, VNC enable, and initial grains-push are bootstrap-only and stay inline.

## 4. Target structure

```
playbooks/
  bootstrap_node.yml          # thin orchestrator (see §5)
  install_salt_master.yml     # ONE playbook (replaces the 4), OS-conditional via salt_master role
  deploy_node_exporter.yml    # keeps working — uses merged node_exporter role
  deploy_telemetry.yml        # NEW (optional) — apply otel_agent + hw_exporter to existing nodes
  group_vars/all.yml          # shared defaults incl. telemetry endpoints
  files/                      # prebuilt exporter + otelcol binaries (air-gap)
  tasks/
    host_prep.yml             # was node_base: Xcode CLT, authorized_keys, VNC, grains-push (deduped)
  roles/
    salt_minion/              # NEW — bootstrap calls ONLY this
      tasks/{main,install_macos,install_debian,install_redhat,configure,service}.yml
    salt_master/              # KEEP+CONSOLIDATE — master + salt-api (tags: api)
    otel_agent/               # NEW — otelcol-contrib + config (hostmetrics + scrape exporters → push) + service
    hw_exporter/              # NEW — apple-silicon / dcgm / amd / cpu-node_exporter by gpu_provider (prebuilt)
    node_exporter/            # MERGE — canonical strong impl; optional, off by default
    node_telemetry/           # NEW — psutil (both OS) + macmon/tart (macOS), via loops
```

**Deleted:** `tasks/bootstrap/{minion_linux,node_deps,node_exporter_linux,node_exporter_macos}.yml`; the weak body of `roles/node_exporter`; `setup_salt_master.yml`, `install_salt_master_linux.yml`, `deploy_salt_master_mm1.yml` (folded into the single `install_salt_master.yml`).

### Role boundaries (one-line contracts)

- **salt_minion** — installs + configures + starts the Salt minion. Input: `salt_masters` (list), `minion_id`, `salt_master_pub_key?`. Output: running minion connected to master(s).
- **salt_master** — installs salt-master (+ salt-api via `--tags api`). Used only by `install_salt_master.yml`.
- **otel_agent** — installs `otelcol-contrib`, renders config (hostmetrics + scrape local exporters), pushes OTLP + remote_write. Input: collector endpoints, node identity. Tags every metric `node_id = minion_id`.
- **hw_exporter** — **auto-detects the accelerator** and installs the matching exporter; `gpu_provider` is a *detected fact*, not a user input (override only for edge cases). Detection: Apple Silicon (`arm64`+Darwin) → `apple-silicon-exporter`; NVIDIA (`nvidia-smi`/`lspci` vendor 10de) → `dcgm-exporter`; AMD (`rocm-smi`/`lspci` vendor 1002) → AMD GPU exporter; none → skip (OTel hostmetrics still covers CPU/mem/disk). All matching prebuilt binaries are vendored in `files/`; only the detected one is installed.
- **node_exporter** — canonical Prometheus node_exporter (arch-aware, checksum, dedicated user). Optional.
- **node_telemetry** — `psutil` (both OS, distro pkg on Linux, pip --user on macOS); `macmon` + `tart` (macOS, brew) installed via a single loop.

## 5. Bootstrap flow

```yaml
# bootstrap_node.yml (sketch)
- hosts: targets
  gather_facts: false
  pre_tasks:
    - detect arch / OS family
    - detect accelerator → set gpu_provider (apple/nvidia/amd/none)
    - gate: salt-master reachable on 4505/4506 (fail fast if none)
  roles:
    - salt_minion                                   # always
    - node_telemetry                                # always (psutil/macmon/tart)
    - hw_exporter                                   # always (auto-detects: apple/dcgm/amd/none)
    - otel_agent                                    # always (hostmetrics + scrape exporters → push)
    - { role: node_exporter, when: node_exporter_enabled | default(false) }
  tasks:
    - import_tasks: tasks/host_prep.yml             # Xcode CLT, authorized_keys, VNC, grains-push
  post_tasks:
    - build masked config summary (set_fact)
    - debug: print summary
    - (kri worker) email summary via kri mailer to SMTP-allowed recipients
```

Telemetry pipeline per node: OTel agent collects OS metrics via the **hostmetrics** receiver and scrapes the local **hw_exporter** (and node_exporter when enabled), tags everything with `node_id = salt.minion_id`, then **pushes** via `otlp` to the OTel gateway (`100.89.50.27:30317`), with optional `otlp/fleet_platform`. (No `prometheusremotewrite`/Victoria Metrics — not present in this cluster; the gateway fans out to Prometheus/Grafana in-cluster.)

## 6. Variable collection (UI + CLI; same vars → extravars)

The collected values become Ansible **extravars**, which override role defaults in `group_vars/all.yml`. The kri worker is non-interactive and always supplies extravars; the `vars_prompt` block only fires for hand-run `ansible-playbook`.

**Mandatory gate:** at least one salt-master address. **New:** manual-IP fallback when no master is registered.

### kri BootstrapModal (canonical)

```
Step 2  Salt Master  (MANDATORY ≥1)
  ◉ Use existing      ☑ mm1 100.102.68.75 [healthy]
  ○ Enter manually    [ 192.168.1.50 ]
Step 3  Telemetry
  Collector (OTLP)        [ <default> ]   (override allowed)
  Victoria remote_write   [ <default> ]
  ☐ Also install node_exporter  :9100  v1.8.2
Step 4  Notify
  Email to [ me@org ▼ ]   (only SMTP-allowed addresses)
```

### Substitution contract

| Field (UI / `vars_prompt`) | extravar | Default (`group_vars/all.yml`) |
|---|---|---|
| Master(s) — existing or manual | `salt_masters` (list) | — (mandatory; no default) |
| Collector OTLP endpoint | `otel_gateway_endpoint` | `100.89.50.27:30317` (OTLP/gRPC; otel-gateway NodePort, Tailscale — **verified live**) |
| Victoria remote_write URL | `victoria_metrics_url` | `""` — **not deployed** in this cluster; exporter omitted |
| Fleet Platform OTLP (optional) | `fleet_platform_otlp` | `""` (disabled) |
| node_exporter toggle | `node_exporter_enabled` | `false` |
| node_exporter listen / version | `node_exporter_listen_address` / `node_exporter_version` | `:9100` / `1.8.2` |
| Telemetry collection interval | `monitoring_interval` | `30s` |
| GPU provider | `gpu_provider` | **auto-detected, not prompted** — apple (Darwin/arm64) / nvidia (10de) / amd (1002) / none; manual override only |
| Notify recipient | `notify_email` | triggering user's email (filtered to `DIGEST_RECIPIENTS`) |

> Endpoints are now resolved against the live environment (verified 2026-06-26): the OTel gateway is reachable at `100.89.50.27:30317` (Tailscale NodePort) and there is no Victoria Metrics. These are deployment config, not design ambiguities.

## 7. Completion summary + email

`post_tasks` assembles a summary and **masks** all sensitive values (SSH password, salt-api password, `node_token`, any OTLP/remote_write auth → `••••`). Contents:

- minion_id, target IP, OS/arch
- salt master(s) used
- collector endpoints (no auth secrets)
- installed components + versions (salt, otelcol, hw_exporter, node_exporter on/off)
- gpu_provider
- per-host result (ok/failed + failed task)

Delivery: the kri worker (which already runs the bootstrap and has DB/mailer access) sends the summary through **kri's existing mailer** — `fleet_platform/services/digest_svc.py::_smtp_send` (port 465 SSL or STARTTLS). SMTP config is read from DB-backed platform settings (`SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM`) via `get_setting_sync`. If `SMTP_HOST` is unset, the email is skipped silently (same as `send_digest`). Recipients = the triggering user and/or a configurable ops list, **filtered to the addresses in the `DIGEST_RECIPIENTS` allow-list** — exactly the "delivered only to configured SMTP recipients" guarantee the harden-approval flow already relies on (`api/routes/node_actions.py`). Non-allowed addresses are dropped with a logged warning. The plaintext summary is also printed to the Ansible log / bootstrap log pane.

## 8. Optimizations (collapse duplication)

- Single canonical `node_exporter` role (eliminates the drift).
- One telemetry pipeline (OTel) instead of node_exporter + OTel hostmetrics double-collection.
- `macmon` + `tart` → one `loop` over a package list; `/etc/salt*` dir creation → `loop`.
- Two grains-push `uri:` tasks → one task with an OS-conditional body dict.
- Shared "resolve URL → version check → download → checksum → extract → install" pattern factored into one reusable task file, reused by salt pkg / node_exporter / otelcol / exporters.

## 9. Compatibility & migration

- `deploy_node_exporter.yml` keeps working against the merged role (variable names unify on `node_exporter_listen_address` / `_version`; map old `node_exporter_port`/`install_dir` during migration).
- The kri worker already passes `salt_masters`, `node_exporter_*` as extravars (#534, #830) — extend with `otel_gateway_endpoint`, `victoria_metrics_url`, `node_exporter_enabled`, `notify_email`.
- Existing bootstrapped nodes are unaffected until re-bootstrapped or targeted by `deploy_telemetry.yml`.
- `salt_master` role internals unchanged; only the wrapper playbooks consolidate.

## 10. Testing

- `ansible-playbook --syntax-check` on `bootstrap_node.yml`, `install_salt_master.yml`, `deploy_telemetry.yml`.
- `ansible-lint` on all new roles.
- Molecule (or check-mode dry-run) per role where feasible: `salt_minion`, `otel_agent`, `hw_exporter`, `node_exporter`, `node_telemetry`.
- Frontend unit test for the BootstrapModal manual-master-IP fallback + endpoint fields.
- Backend unit test: extravars assembly includes the new telemetry vars; summary masker redacts secrets; recipient filter rejects non-SMTP-configured addresses.
- One real end-to-end bootstrap on a macOS node and a Linux node before fleet-wide rollout.

## 11. Environment findings (verified 2026-06-26 from the kri host `cylon` / `192.168.1.10` / `100.89.50.27`)

- **No monitoring stack on host ports.** `:8428` (Victoria Metrics), `:4317/:4318`, `:9090`, `:3000` are all closed; no victoria/otel/prometheus docker containers. `http://192.168.1.10:8428` does not exist — that was a placeholder echoed from hydra docs.
- **The stack lives in k8s `monitoring` namespace:** kube-prometheus-stack (`monitoring-prometheus`), `monitoring-grafana`, `monitoring-prometheus-node-exporter`, and **`otel-gateway`** (pod Running 26h).
- **`otel-gateway` is exposed via NodePort** — `4317:30317` (OTLP gRPC), `4318:30318` (OTLP HTTP), `13133:31396` (health), `8889:31099`. Health returns 200 and OTLP HTTP returns 405 on GET (alive). Reachable on both the LAN IP (`192.168.1.10`) and the Tailscale IP (`100.89.50.27`).
- **Push target decision:** agents push OTLP/gRPC to **`100.89.50.27:30317`** (Tailscale, fleet-reachable — matches the existing `ingest_url` convention). The VM remote_write exporter from hydra's template is omitted.
- An in-cluster node-exporter already exists; combined with OTel hostmetrics this further justifies node_exporter being optional/off for fleet nodes.

## 12. Open inputs (still needed before/at implementation)

1. ~~Collector endpoints~~ — **resolved:** `otel_gateway_endpoint = 100.89.50.27:30317` (verified). Confirm whether the otel-gateway accepts plain OTLP without auth/TLS from fleet nodes (NodePort GET worked unauthenticated; a real OTLP POST should be smoke-tested during implementation).
2. ~~Which exporter binaries~~ — **resolved:** vendor **all three** (apple-silicon, dcgm, amd); `hw_exporter` auto-detects the accelerator and installs only the matching one. (Need to obtain/build the prebuilt binaries at implementation time.)
3. ~~kri SMTP/allowed-recipient config~~ — **resolved:** reuse `digest_svc._smtp_send` + platform settings `SMTP_*`; recipient allow-list = `DIGEST_RECIPIENTS`.
