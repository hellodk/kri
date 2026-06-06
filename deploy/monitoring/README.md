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
