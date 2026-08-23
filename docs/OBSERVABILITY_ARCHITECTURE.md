# kri Fleet Platform — Observability Architecture

## Overview

kri instruments every significant runtime path with metrics, structured logs, and distributed traces. This document describes how each signal travels from the code to storage and ultimately to dashboards and alerts.

---

## Data-Flow Diagram (text)

```
fleet_platform code
  │
  ├─ prometheus-client counters/gauges
  │    ↓
  │  FastAPI /metrics endpoint (job=kri-api)
  │    ↓
  │  Prometheus scrape (ServiceMonitor, kri namespace)
  │    ├─→ Alertmanager  →  alert notifications
  │    └─→ Grafana       →  dashboards
  │
  ├─ structlog JSON → stdout → Promtail → Loki
  │
  └─ OTEL SDK → spans → OTLP → Tempo (avika/avika-tempo)
```

---

## 1. Metrics Pillars

### 1.1 HTTP request metrics

| Metric | Type | Labels |
|--------|------|--------|
| `kri_http_requests_total` | Counter | `method`, `path`, `status_code` |
| `kri_http_request_duration_seconds` | Histogram | `method`, `path` |

Source: `PrometheusMiddleware` wrapping every FastAPI route.

### 1.2 Node-action lifecycle metrics (issue #661)

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `kri_node_action_total` | Counter | `action_type`, `status` | Incremented at each lifecycle transition. `status` values: `requested`, `approved`, `rejected`, `executed`, `failed`. |
| `kri_pending_action_queue_depth` | Gauge | — | Count of actions in `requested` state waiting for approval. Refreshed at scrape time via a Prometheus `Gauge.set()` call. |

Data flow: `fleet_platform/services/node_action_svc.py` → `kri_node_action_total.labels(...).inc()` → `/metrics` → Prometheus → Grafana panel "Node Action Rate by Status" + alert `KriNodeActionFailureRateHigh`.

### 1.3 Process-stats ingest counters (issue #661)

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `kri_process_stats_rows_ingested_total` | Counter | — | Rows successfully written to the DB per ingest batch. |
| `kri_process_stats_rows_dropped_total` | Counter | — | Rows discarded because the payload exceeded the configured cap. |

Data flow: `fleet_platform/services/digest_svc.py` → counters incremented per batch → `/metrics` → Prometheus → Grafana panel "Ingest Throughput & Drops" + alert `KriProcessStatsIngestDrops`.

### 1.4 Salt dispatch counter (issue #661)

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `kri_salt_dispatch_total` | Counter | `function`, `outcome` | Every call to the guarded Salt dispatch path. `outcome`: `ok` or `error`. |

Data flow: `fleet_platform/services/salt_dispatch_svc.py` → `kri_salt_dispatch_total.labels(...).inc()` → `/metrics` → Prometheus → Grafana panel "Salt Dispatch Rate by Outcome" + alert `KriSaltDispatchErrors`.

### 1.5 Availability / heartbeat metrics

| Metric | Type | Description |
|--------|------|-------------|
| `up{job="kri-api"}` | Gauge (synthetic) | 1 if Prometheus can scrape `/metrics`; 0 otherwise. |
| `kri_beat_last_run_timestamp_seconds` | Gauge | Unix timestamp of last `mark_stale_nodes` Celery beat run. |
| `kri_node_ssh_reachable` | Gauge | 1/0 per node SSH reachability probe. |

### 1.6 Other metrics

| Metric | Type |
|--------|------|
| `kri_nodes_total` | Gauge |
| `kri_nodes_online` | Gauge |
| `kri_nodes_offline` | Gauge |
| `kri_ssh_sessions_active` | Gauge |
| `kri_celery_tasks_total` | Counter |
| `kri_http_requests_total` | Counter |

---

## 2. Scrape Configuration

**Kubernetes:** `deploy/k8s/observability/service-monitor.yaml` — `ServiceMonitor` in the `kri` namespace, label `release: monitoring` (matches kube-prometheus-stack's `serviceMonitorSelector`).

**docker-compose / standalone:** Add a static scrape target in `prometheus.yml`:
```yaml
scrape_configs:
  - job_name: kri-api
    static_configs:
      - targets: ["<kri-api-host>:8000"]
```

---

## 3. Alert Rules

Alert rules are defined in two mirrored files:

| File | Purpose |
|------|---------|
| `deploy/monitoring/rules/kri-alerts.rules.yml` | Portable — referenced directly by Prometheus via `rule_files:` in docker-compose and standalone modes. |
| `deploy/k8s/observability/kri-prometheusrule.yaml` | Kubernetes `PrometheusRule` CR — `spec.groups` content mirrors the portable file exactly. |

### Alert inventory

| Alert Name | Severity | Fires When |
|------------|----------|-----------|
| `KriAPIDown` | critical | `up{job="kri-api"} == 0` for 2 m |
| `KriWorkerDown` | critical | `kri_beat_last_run_timestamp_seconds == 0` for 5 m |
| `KriBeatHeartbeatExpired` | warning | beat timestamp > 10 min stale for 5 m |
| `KriNodeSSHUnreachable` | warning | `kri_node_ssh_reachable == 0` for 30 m |
| `KriAPIErrorRateHigh` | warning | 5xx rate > 5 % for 5 m |
| `KriAPILatencyP99High` | warning | p99 latency > 5 s for 10 m |
| `KriApprovalQueueDeep` | warning | `kri_pending_action_queue_depth > 10` for 10 m — admin not approving queued node actions |
| `KriNodeActionFailureRateHigh` | warning | `sum(rate(kri_node_action_total{status="failed"}[10m])) > 0.2` for 10 m |
| `KriProcessStatsIngestDrops` | warning | `rate(kri_process_stats_rows_dropped_total[10m]) > 0` for 15 m — payload cap dropping rows |
| `KriSaltDispatchErrors` | warning | `sum(rate(kri_salt_dispatch_total{outcome="error"}[10m])) > 0.1` for 10 m |

---

## 4. Grafana Dashboards

| ConfigMap | UID | Contents |
|-----------|-----|----------|
| `kri-dashboard` (`grafana-dashboard.yaml`) | `kri-fleet` | Node overview, SSH reachability, HTTP rate, p99 latency, Celery task rate |
| `kri-dashboard-actions` (`grafana-dashboard-actions.yaml`) | `kri-actions-ingest` | Node action rate by status, approval queue depth, ingest throughput + drops, Salt dispatch by outcome |

Both ConfigMaps carry label `grafana_dashboard: "1"` in the `kri` namespace. Grafana's sidecar injects them automatically.

---

## 5. Structured Logging

All log lines are emitted as JSON via `structlog` with mandatory fields:

```json
{
  "level": "info",
  "timestamp": "2026-06-09T10:00:00Z",
  "service": "kri-api",
  "trace_id": "<otel-trace-id>"
}
```

Logs flow: pod stdout → Promtail (DaemonSet) → Loki. Query in Grafana Explore with `{namespace="kri"}`.

---

## 6. Distributed Tracing

kri uses the OTEL Python SDK. Spans are exported via OTLP gRPC to `avika-tempo.avika.svc.cluster.local:4317`.

Instrumented paths:
- All FastAPI HTTP handlers (`otelhttp`)
- All DB queries (SQLAlchemy instrumentation)
- All Salt dispatch calls (manual span)
- All Celery tasks (OTEL Celery instrumentation)

`trace_id` is injected into every structlog log line via a structlog processor that reads the active OTEL span context.

---

## 7. Deployment-Mode Observability Reference

| Concern | docker-compose | kubernetes | standalone |
|---------|---------------|-----------|-----------|
| Scrape config | `prometheus.yml` static target | `ServiceMonitor` CR | `prometheus.yml` static target |
| Alert rules | `rule_files: [kri-alerts.rules.yml]` | `PrometheusRule` CR | `rule_files: [kri-alerts.rules.yml]` |
| Dashboards | Import `kri.json` + `kri-actions.json` manually | `ConfigMap` with `grafana_dashboard: "1"` | Import manually |
| Traces | OTLP to local Tempo or Jaeger | OTLP to `avika-tempo.avika.svc.cluster.local` | OTLP to local Tempo |
| Logs | Promtail container sidecar | Promtail DaemonSet | Promtail systemd unit |

---

## 8. Realtime Troubleshooting (#1052)

Every inbound HTTP request gets a correlation id, and every Celery task carries its own, so a single grep joins an API call to everything it triggered.

| Field | Set by | Scope |
|-------|--------|-------|
| `trace_id` | structlog processor reading the active OTEL span (falls back to UUID4) | Every log line, API and worker — same value Tempo indexes |
| `request_id` | `RequestContextMiddleware` (client `X-Request-ID`, else 12-char hex) | One HTTP request; echoed back as the `X-Request-ID` response header |
| `method`, `path` | `RequestContextMiddleware` | One HTTP request |
| `task_id`, `task_name` | `task_prerun`/`task_postrun` signals in `workers/celery_app.py` | One Celery task execution on a worker slot |

### Grep / jq recipes

Raw pod stdout (works even when Loki is down):

```bash
# Everything that happened inside one API request
kubectl logs -n kri -l app=kri-api --prefix --tail=-1 \
  | jq -c 'select(.request_id=="9f2c41d0a8b3")'

# One trace across API and workers (same trace_id on both sides)
kubectl logs -n kri -l app=kri-api --prefix --tail=-1   | jq -c 'select(.trace_id=="<32-hex>")'
kubectl logs -n kri -l app=kri-worker --prefix --tail=-1 | jq -c 'select(.trace_id=="<32-hex>")'

# All worker lines for one task execution
kubectl logs -n kri -l app=kri-worker --prefix --tail=-1 \
  | jq -c 'select(.task_id=="<uuid>")'

# Everything touching one node (minion id)
kubectl logs -n kri -l app=kri-api --prefix --tail=-1    | jq -c 'select(.minion_id=="node-42")'
kubectl logs -n kri -l app=kri-worker --prefix --tail=-1 | jq -c 'select(.minion_id=="node-42")'
```

The same filters in Grafana Explore / LogQL:

```logql
{namespace="kri"} | json | request_id="9f2c41d0a8b3"
{namespace="kri"} | json | task_name="fleet_platform.workers.playbook_tasks.run_playbook"
{namespace="kri"} | json | minion_id="node-42" | line_format "{{.timestamp}} {{.level}} {{.message}}"
```

### Tempo link flow

1. Copy `trace_id` from any JSON log line (or `X-Request-ID` → grep for `request_id` → grab its `trace_id`).
2. Grafana Explore → Tempo datasource → paste the id into **TraceQL** (`<trace_id>` or `trace:id="..."`) → open the trace.
3. The trace starts at the FastAPI server span; child spans show SQLAlchemy queries and outbound httpx calls. If the request dispatched a task, the OTEL Celery instrumentation propagates the trace context through the broker message headers, so the worker-side task span appears in the **same trace**.
4. From a worker span back to logs: its `task_id` attribute matches the `task_id` field in the JSON lines above.

### Worked example — playbook run stuck at 40%

Symptom: UI shows bootstrap run `b7e1...` stuck at 40% for 20 minutes.

1. Grab `X-Request-ID` from the failed API response: `req-id = 9f2c41d0a8b3`.
2. `{namespace="kri"} | json | request_id="9f2c41d0a8b3"` → last API line is `POST /api/nodes/42/bootstrap 202`, carrying `task_id=<uuid>` and `trace_id=<t>`.
3. Open Tempo with `<t>`: API span → `run_playbook` producer span ends fine — so enqueue succeeded; the stall is worker-side.
4. `jq -c 'select(.task_id=="<uuid>")'` over worker pods → last line before the gap is `ansible-playbook ... timeout=1800s`, then `SoftTimeLimitExceeded`.
5. Conclusion: node SSH blackholed mid-run until the 30-minute soft limit fired. Remediation is in the runbook (check node firewall); the alert `kri_worker_task_timeout` should have fired alongside.

If a log line has no `request_id`/`task_id`, either it ran outside both contexts (beat-scheduled task start-up lines) or the middleware/signals did not run — check pod startup logs for `configure_logging` errors first.
