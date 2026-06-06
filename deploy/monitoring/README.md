# kri Observability — wiring for all three deployment modes

kri exposes Prometheus metrics at **`/metrics`** (unauthenticated) on the API
port. The alert rules live in **`rules/kri-alerts.rules.yml`** (portable) and are
mirrored into a k8s `PrometheusRule` at
`../k8s/observability/kri-prometheusrule.yaml`.

Per the multi-mode deployment rule, every observability artifact is wired for
**docker-compose**, **kubernetes**, and **standalone**. Pick your mode below.

## Key metrics
| Metric | Source | Meaning |
|--------|--------|---------|
| `kri_node_ssh_reachable{minion_id}` | `connectivity_tasks.check_ssh_connectivity` (Celery beat, 15 min) → redis → `/metrics` | `1` reachable, `0` unreachable (#356) |

---

## Mode 1 — docker-compose
Add to your Prometheus `scrape_configs` (see `prometheus-scrape-examples.yml`,
job `kri-compose`, target `api:8000`) and load the rules:
```yaml
rule_files:
  - /etc/prometheus/rules/kri-alerts.rules.yml   # mount rules/kri-alerts.rules.yml here
```

## Mode 2 — kubernetes
```bash
kubectl create namespace kri --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -f deploy/k8s/observability/service-monitor.yaml      # scrape (needs a kri Service labelled app=kri-api)
kubectl apply -f deploy/k8s/observability/kri-prometheusrule.yaml   # alerts
```
Both carry `release: monitoring` so the kube-prometheus-stack operator selects
them. The ServiceMonitor lives in the `kri` namespace (never `monitoring`).

> If kri runs in **docker-compose on the same host as the cluster** (the common
> dev setup — the k0s node and the compose stack share a host), there is no kri
> Service for the ServiceMonitor to select. Instead scrape the host's published
> port: apply the `PrometheusRule` for alerts, and add a static scrape (job
> `kri-standalone`, target `<host-ip>:80`) via the Prometheus
> `additionalScrapeConfigs` secret.

## Mode 3 — standalone (Linux / Mac Mini)
Point any Prometheus at the host (see `prometheus-scrape-examples.yml`, job
`kri-standalone`, replace `KRI_HOST`) and load `rules/kri-alerts.rules.yml` via
`rule_files`. No k8s required.

---

**Rule of thumb:** the *rule* (`rules/kri-alerts.rules.yml`) is identical
everywhere; only the *scrape path* and *rule delivery* (rule_files vs
PrometheusRule CR) differ by mode. Keep the two rule files in sync.

---

## Grafana dashboard

The dashboard JSON lives at **`deploy/monitoring/dashboards/kri.json`**
(uid `kri-fleet`, title `kri Fleet Platform`, schemaVersion 39, Grafana 10/11).

It covers:
- Stat row: Nodes Online / Offline / Total, SSH Sessions Active
- Timeseries: SSH Reachability per Node (`kri_node_ssh_reachable` by `minion_id`)
- Timeseries: HTTP Request Rate (`sum(rate(kri_http_requests_total[5m]))`)
- Timeseries: p99 Latency (`histogram_quantile(0.99, …kri_http_request_duration_seconds_bucket…)`)
- Timeseries: Celery Task Rate (`rate(kri_celery_tasks_total[5m])`)

### docker-compose / standalone import

In Grafana UI: **Dashboards → Import → Upload JSON file** → select
`deploy/monitoring/dashboards/kri.json`. Choose your Prometheus datasource
when prompted for `DS_PROMETHEUS`.

Alternatively, copy the file into Grafana's provisioned dashboard directory
and set `updateIntervalSeconds: 30` in the provisioning config.

### kubernetes — automatic via Grafana sidecar

Apply the ConfigMap once; the Grafana sidecar (label selector `grafana_dashboard: "1"`)
picks it up automatically within ~30 seconds:

```bash
kubectl apply -f deploy/k8s/observability/grafana-dashboard.yaml
```

The ConfigMap lives in the **`kri` namespace** (not `monitoring`). The JSON
embedded in `data.kri.json` must stay byte-identical to
`deploy/monitoring/dashboards/kri.json` — update both files together.
