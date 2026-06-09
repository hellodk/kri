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
