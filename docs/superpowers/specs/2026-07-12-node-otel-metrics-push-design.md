# Node Host-Metrics via OTEL Push + Monitoring Decoupling

**Status:** design · **Date:** 2026-07-12 · **Owner:** kri

## Problem

Three related defects, all confirmed from a real bootstrap run log (`192.168.1.64`, 2026-07-11):

1. **Monitoring is hostage to Salt.** `node_exporter` is installed by `bootstrap_node.yml`, but it runs *after* the salt-master reachability gate (pre_tasks) and the `salt_minion` install role. When the master is unreachable (as in the log — ports 4505/4506/4507 refused), Ansible aborts the play for that host before `node_exporter` — or, once the corrected `wait_for` gate ships, the gate itself fails the host early. Either way monitoring silently doesn't happen.
2. **Metrics are pull-based with manual scrape config.** `deploy/monitoring/prometheus-scrape-examples.yml` uses `static_configs` with placeholders. A freshly bootstrapped node's `:9100` is never auto-registered, so nothing scrapes it → "Metrics not available" even when `node_exporter` is running.
3. **Redundant manual rescue.** A "Deploy Monitoring" button + standalone `deploy_node_exporter.yml` exist only to work around (1)/(2).

## Goals

- Every bootstrapped node **pushes** host metrics reliably, independent of salt/master state.
- No manual Prometheus scrape registration.
- Remove the redundant "Deploy Monitoring" button and `deploy_node_exporter.yml`.
- kri asks the operator for the OTLP endpoint, pre-filled with a verified default, editable.

## Non-goals (YAGNI)

- Replacing `node_exporter` with the OTEL `hostmetrics` receiver (decided: keep node_exporter as the source).
- Per-node different metric pipelines.
- Building a new metrics store — reuse the cluster's existing Prometheus/Grafana behind the gateway.

## Design

### Collection + push (per node)

- **Keep `node_exporter`**, bound to `127.0.0.1:9100` (localhost only — it is no longer scraped remotely).
- New **`otel_collector` role** installs `otelcol-contrib` (pinned version) configured with:
  - **prometheus receiver** scraping `127.0.0.1:9100` (node_exporter),
  - **OTLP exporter** → the configured endpoint,
  - an OS-appropriate service (launchd on macOS, systemd on Linux).
- The role is **decoupled from Salt**: it runs in its own play (or an early `block` with `rescue`) so a salt-master failure can never abort it. This is the core fix for defect (1).

### Configuration — kri asks the operator

New `PlatformSetting` keys (reusing the existing settings table + Settings → Bootstrap UI, same mechanism as `ingest_url`/`controller_pubkey`):

| Setting | Default | Notes |
|---------|---------|-------|
| `otlp_endpoint` | `http://<k0s-host>:30318` (otel-gateway NodePort, HTTP) | **Verified running**: `monitoring/otel-gateway`, NodePort 30317 gRPC / 30318 HTTP. Pre-filled, operator **must verify/correct** the host — off-cluster nodes reach it on the k0s host's LAN IP. |
| `otlp_protocol` | `http` | `http` (4318/30318) or `grpc` (4317/30317). |
| `otlp_headers` | empty | Optional auth header, stored **encrypted** (like other secrets). |

These are passed to `bootstrap_node.yml` as extravars (`otlp_endpoint`, `otlp_protocol`, `otlp_headers`) exactly like `ingest_url`/`node_token`.

### kri UI reads metrics

The Node → Resources tab currently expects to reach `:9100` directly. With push, kri queries the **metrics backend (Prometheus behind the gateway)** instead. *(Flagged: this is a wiring change dependent on the gateway → Prometheus path; see Open Questions.)*

### Removals

- Delete the "Deploy Monitoring" button and its wiring: `OverviewTab.tsx`, `ResourcesTab.tsx`, `api/ansible.ts`, `BootstrapModal.tsx` (+ test).
- Delete standalone `playbooks/deploy_node_exporter.yml`.
- The corrected `wait_for` reachability gate (already in Phase-3 `host_prep_gate.yml`) ships as-is; because monitoring now runs in its own play, the gate can no longer suppress it.

## Phasing (each its own issue + PR + tests)

1. **Decouple monitoring** — move `node_exporter` + new `otel_collector` into their own play/block; ship the gate fix. *(makes "every node gets monitoring via bootstrap" reliably true — prerequisite for removing the button)*
2. **OTEL config** — `PlatformSetting` keys + Settings UI prompt (default gateway, verifiable, encrypted header) + extravar wiring + the `otel_collector` role.
3. **Remove Deploy Monitoring** — button + `deploy_node_exporter.yml`.
4. **Rewire Resources tab** — read node metrics from the metrics backend instead of `:9100`.

## Tests

- `otel_collector` role: config renders the prometheus receiver (`127.0.0.1:9100`) + OTLP exporter; service defined per-OS; **no salt dependency** (contract).
- Decoupling: `node_exporter`/`otel_collector` run even when the salt gate would fail the host (play-structure contract test).
- Settings: OTLP settings CRUD, default value, header stored encrypted, extravar propagation.
- Removal: no `/deploy-monitoring` route/handler remains, button gone from UI, `deploy_node_exporter.yml` absent.

## Open questions / flags

- **Off-cluster reachability:** Mac nodes reach the gateway via NodePort on the k0s host's **LAN** IP (per the LAN-over-Tailscale rule). That host IP is not known here — hence the mandatory verify/correct prompt. The pre-filled default host is a best guess the operator confirms.
- **Air-gap:** `otelcol-contrib` must be available offline. Like the salt pkg, the pinned binary/checksum should be bundled under `playbooks/files/` (ties into the pending air-gap salt work). macOS: pinned binary rather than a brew formula, to keep versions deterministic.
- **Resources-tab rewiring (Phase 4)** depends on the gateway → Prometheus query path being reachable from the kri backend.

## Related

- Sibling spec (separate): master-promotion + minion re-point epic (additive-HA, thin reconfigure playbook, phased C→B→A).
- Depends on the roles-refactor (Phases 1–3, merged) for the role/thin-orchestrator structure.
