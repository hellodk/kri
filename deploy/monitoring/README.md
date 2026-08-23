# kri Observability — VictoriaMetrics stack (#1051)

kri exposes Prometheus-format metrics at **`/metrics`** on the API port,
protected by a **bearer token** (`METRICS_TOKEN`). The metrics pipeline is
**VictoriaMetrics** (storage + query), fed by **vmagent** (scrape) and
evaluated by **vmalert** (rules). Alert rules live in
**`rules/kri-alerts.rules.yml`** — one portable file used by every mode — and
are mirrored into a k8s `PrometheusRule` at
`../k8s/observability/kri-prometheusrule.yaml`.

## Architecture

```
                    METRICS_TOKEN (bearer)
                            │
 ┌──────────────┐  scrape   ▼          remote_write      ┌──────────────────┐
 │ kri api      │──── /metrics ──┐   /api/v1/write        │ VictoriaMetrics  │
 │ :8000        │                │   ┌───────────┐        │ :8428            │
 └──────────────┘                └──▶│ vmagent   │───────▶│  -retention=90d  │
                                     │ :8429     │        │                  │
 ┌──────────────┐   rules file       └───────────┘        └────────▲─────────┘
 │ vmalert      │◀── /etc/vmalert/*.yml                           │ queries
 │              │──── evaluate against datasource.url ============┘
 └──────────────┘                                                     ▲
                                                                      │ PromQL
                                                               ┌──────┴───────┐
                                                               │ Grafana      │
                                                               │ (datasource: │
                                                               │ KRI-Victoria-│
                                                               │ Metrics)     │
                                                               └──────────────┘
```

Per the multi-mode deployment rule, observability is wired for
**docker-compose**, **kubernetes**, and **standalone**. Pick your mode below.

## Key metrics
| Metric | Source | Meaning |
|--------|--------|---------|
| `kri_node_ssh_reachable{minion_id}` | `connectivity_tasks.check_ssh_connectivity` (Celery beat, 15 min) → redis → `/metrics` | `1` reachable, `0` unreachable (#356) |

## METRICS_TOKEN

The API `/metrics` endpoint expects the bearer token from `METRICS_TOKEN`.
Generate one:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

Put it in `.env.docker` (compose modes) or in the k8s Secrets below. The same
value is shared by the API (validation) and the scrapers (presentation).

---

## Mode 1 — docker-compose (optional dedicated monitoring stack)

A self-contained VictoriaMetrics + vmagent + vmalert stack ships at
`docker-compose.monitoring.yml`. All images are pinned to `v1.150.0`.

```bash
cd /path/to/kri
export METRICS_TOKEN=$(python3 -c 'import secrets; print(secrets.token_hex(32))')
docker compose -f deploy/monitoring/docker-compose.monitoring.yml up -d
```

* VictoriaMetrics UI/API: `http://127.0.0.1:8428` (loopback only), data in the
  `vmdata` volume, retention 90 days.
* vmagent scrapes `api:8000/metrics` per `vmagent-scrape.yml` and remote-writes
  to VM.
* vmalert evaluates `rules/kri-alerts.rules.yml` against VM. The notifier flag
  is commented out — uncomment `- -notifier.url=http://alertmanager:9093` once
  an Alertmanager runs alongside.

If you instead run your own Prometheus, copy the `scrape_configs` entry from
`vmagent-scrape.yml` into your `prometheus.yml` (it carries the bearer-token
`authorization` block) and load the rules via `rule_files:`.

## Mode 2 — kubernetes

```bash
kubectl apply -k deploy/k8s/
# …or apply just the observability slice:
kubectl apply -f deploy/k8s/observability/vm-agent.yaml
kubectl apply -f deploy/k8s/observability/kri-prometheusrule.yaml
kubectl apply -f deploy/k8s/observability/grafana-dashboard.yaml
kubectl apply -f deploy/k8s/observability/grafana-datasource.yaml
```

Secrets needed before first apply (namespace `kri`):

```bash
kubectl -n kri create secret generic kri-metrics-token \
  --from-literal=METRICS_TOKEN="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
# plus the existing kri-secrets bundle (see deploy/k8s/secret.yaml.template),
# which must now also carry a METRICS_TOKEN key for the api Deployment env.
```

* `observability/vm-agent.yaml` deploys vmagent as a plain
  Deployment + ConfigMap + Service — there is **no prometheus-operator /
  ServiceMonitor** in this cluster (the former `service-monitor.yaml` was
  removed). The scrape config targets `kri-api:8000` with bearer credentials
  from the `kri-metrics-token` Secret; an optional `kubernetes_sd_configs`
  variant is included as a comment block.
* The Grafana datasource ConfigMap points at
  `http://victoriametrics.monitoring.svc:8428` (datasource name
  `KRI-VictoriaMetrics`, type `prometheus` — VictoriaMetrics speaks the
  Prometheus query API). Deploy VictoriaMetrics itself into the `monitoring`
  namespace of your cluster (e.g. via the compose stack above adapted, or the
  vendor's official chart).

> If kri runs in **docker-compose on the same host as the cluster**, no kri
> Service is reachable from in-cluster vmagent. Scrape the host's published
> nginx port instead: edit the static target in `vm-agent.yaml`'s ConfigMap
> (job stays `kri-api`) or add a static target on the compose-mode vmagent.

## Mode 3 — standalone (Linux / Mac Mini)

Point vmagent (or any Prometheus) at the host: set the target in
`vmagent-scrape.yml` to `<KRI_HOST>:80`, keep `job_name: kri-api`, then run
the compose monitoring stack from Mode 1 with that config mounted. No k8s
required.

---

## Rule & dashboard compatibility notes

* **Rules are unchanged.** `rules/kri-alerts.rules.yml` is standard
  Prometheus alerting/recording syntax; VictoriaMetrics (and vmalert) are
  fully compatible — including `up{job="kri-api"} == 0` (KriAPIDown) and the
  `$labels.minion_id` templating. Keep it byte-compatible with its mirror in
  `../k8s/observability/kri-prometheusrule.yaml`.
* **Job names matter.** KriAPIDown matches `up{job="kri-api"}` — both shipped
  scrape configs use exactly that job name.
* **Dashboards are unchanged.** `dashboards/kri.json` (uid `kri-fleet`) uses
  only Prometheus-datasource queries, which work verbatim against
  VictoriaMetrics through the Grafana Prometheus datasource. Import via
  **Dashboards → Import → Upload JSON file**, or rely on the sidecar label
  (`grafana_dashboard: "1"`) in k8s mode. The JSON embedded in
  `deploy/k8s/observability/grafana-dashboard.yaml` must stay byte-identical
  to `dashboards/kri.json` — update both together.

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
`deploy/monitoring/dashboards/kri.json`. Choose your VictoriaMetrics
datasource (Prometheus-compatible) when prompted for `DS_PROMETHEUS`.

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
