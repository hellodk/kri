"""
Manifest-contract tests for the #1050 deploy-hardening + #1051 VictoriaMetrics
migration changes:

- deploy/docker-compose.yml          (stop_grace_period, redis maxmemory,
                                      api entrypoint wiring)
- deploy/api-entrypoint.sh           (chown + migrate + exec uvicorn)
- deploy/k8s/beat-deployment.yaml    (replicas: 2 — RedBeat lock election)
- deploy/k8s/network-policy.yaml     (monitoring ingress 8000, RFC1918
                                      SSH/salt-api egress, OTLP 4317/4318)
- deploy/k8s/kustomization.yaml      (observability in, configmap.yaml out)
- deploy/monitoring/                 (vmagent-scrape.yml, compose monitoring
                                      stack pinned v1.150.0)
- deploy/k8s/observability/vm-agent.yaml (vmagent Deployment + ConfigMap +
                                      Service replacing the ServiceMonitor)

Every changed YAML is parsed with yaml.safe_load / safe_load_all to prove
structural validity; assertions pin the contract-relevant content.
"""

import os
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEPLOY = _REPO_ROOT / "deploy"


def _read(path: Path) -> str:
    assert path.exists(), f"missing required file: {path}"
    return path.read_text()


def _load_compose() -> dict:
    return yaml.safe_load(_read(_DEPLOY / "docker-compose.yml"))


# ---------------------------------------------------------------------------
# #1050 — docker-compose hardening
# ---------------------------------------------------------------------------


class TestComposeGracePeriods:
    def test_ansible_worker_3700s(self):
        svc = _load_compose()["services"]["worker-ansible"]
        assert svc["stop_grace_period"] == "3700s"

    def test_default_worker_2200s(self):
        svc = _load_compose()["services"]["worker"]
        assert svc["stop_grace_period"] == "2200s"

    def test_beat_2200s(self):
        svc = _load_compose()["services"]["beat"]
        assert svc["stop_grace_period"] == "2200s"


class TestComposeRedisMemory:
    def test_maxmemory_512mb_noeviction(self):
        cmd = _load_compose()["services"]["redis"]["command"]
        assert "--maxmemory 512mb" in cmd
        assert "--maxmemory-policy noeviction" in cmd


class TestApiEntrypoint:
    def test_entrypoint_script_exists_and_executable(self):
        script = _DEPLOY / "api-entrypoint.sh"
        assert script.exists()
        assert os.access(script, os.X_OK)

    def test_entrypoint_chowns_then_execs_uvicorn(self):
        text = _read(_DEPLOY / "api-entrypoint.sh")
        assert ".kri/git-repos" in text
        assert "exec uv run uvicorn fleet_platform.api.main:app" in text
        assert "bash /app/deploy/migrate.sh" in text

    def test_api_service_uses_entrypoint_and_init(self):
        api = _load_compose()["services"]["api"]
        assert api["command"] == ["bash", "/app/deploy/api-entrypoint.sh"]
        assert api["init"] is True


# ---------------------------------------------------------------------------
# #1050 — kubernetes beat HA
# ---------------------------------------------------------------------------


def test_beat_deployment_replicas_two_with_redbeat_comment():
    path = _DEPLOY / "k8s" / "beat-deployment.yaml"
    doc = yaml.safe_load(_read(path))
    assert doc["spec"]["replicas"] == 2
    raw = _read(path)
    assert "RedBeat" in raw, "replicas bump must cite the RedBeat lock election"


# ---------------------------------------------------------------------------
# #1050 — real beat healthcheck (redis ping + redbeat:* scan)
# ---------------------------------------------------------------------------


def test_compose_beat_healthcheck_scans_redbeat_keys():
    hc = _load_compose()["services"]["beat"]["healthcheck"]["test"]
    joined = " ".join(str(part) for part in hc)
    assert "redbeat:" in joined
    assert "settings.redis_url" in joined or "redis_url" in joined


def test_beat_deployment_probes_scan_redbeat_keys():
    ctn = yaml.safe_load(_read(_DEPLOY / "k8s" / "beat-deployment.yaml"))["spec"]["template"]["spec"]["containers"][0]
    for probe_name in ("livenessProbe", "readinessProbe"):
        probe = ctn[probe_name]["exec"]["command"]
        joined = " ".join(str(part) for part in probe)
        assert "redbeat:" in joined, f"{probe_name} must check redbeat keys"
        assert "tautological" not in joined


# ---------------------------------------------------------------------------
# #1050 — network policy: monitoring scrape, fleet SSH/salt-api, OTLP
# ---------------------------------------------------------------------------


def _network_policies() -> list:
    return [
        d
        for d in yaml.safe_load_all(_read(_DEPLOY / "k8s" / "network-policy.yaml"))
        if d and d.get("kind") == "NetworkPolicy"
    ]


def test_network_policy_api_ingress_from_monitoring_on_8000():
    found = False
    for policy in _network_policies():
        if "Ingress" not in policy.get("spec", {}).get("policyTypes", []):
            continue
        selector = (policy.get("spec", {}).get("podSelector", {}) or {}).get("matchExpressions", [])
        targets_api = any(rule.get("key") == "component" and "api" in rule.get("values", []) for rule in selector)
        for ingress in policy["spec"].get("ingress", []) or []:
            ports = ingress.get("ports", []) or []
            has_8000 = any(p.get("port") == 8000 and p.get("protocol") == "TCP" for p in ports)
            from_monitoring = any(
                ns.get("namespaceSelector", {}).get("matchLabels", {}).get("kubernetes.io/metadata.name")
                == "monitoring"
                for src in ingress.get("from", []) or []
                for ns in [src]
            )
            if targets_api and has_8000 and from_monitoring:
                found = True
    assert found, "no NetworkPolicy allows tcp/8000 to component=api from monitoring"


def test_network_policy_rfc1918_ssh_and_salt_api_egress():
    rfc1918 = {"10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"}
    found = False
    for policy in _network_policies():
        spec = policy.get("spec", {})
        expr = (spec.get("podSelector", {}) or {}).get("matchExpressions", [])
        components = set()
        for rule in expr:
            if rule.get("key") == "component":
                components.update(rule.get("values", []))
        if not {"api", "worker", "worker-ansible"} <= components:
            continue
        for egress in spec.get("egress", []) or []:
            ips = {t.get("ipBlock", {}).get("cidr") for t in egress.get("to", []) or [] if "ipBlock" in t}
            ports = {p.get("port") for p in egress.get("ports", []) or []}
            if rfc1918 <= ips and {22, 8080} <= ports:
                found = True
    assert found, "no egress allows RFC1918 on 22/8080 for api+workers"


def test_network_policy_otlp_egress_to_monitoring():
    found = False
    for policy in _network_policies():
        spec = policy.get("spec", {})
        expr = (spec.get("podSelector", {}) or {}).get("matchExpressions", [])
        components = set()
        for rule in expr:
            if rule.get("key") == "component":
                components.update(rule.get("values", []))
        if not {"api", "worker", "worker-ansible"} <= components:
            continue
        for egress in spec.get("egress", []) or []:
            to_monitoring = any(
                t.get("namespaceSelector", {}).get("matchLabels", {}).get("kubernetes.io/metadata.name") == "monitoring"
                for t in egress.get("to", []) or []
            )
            ports = {p.get("port") for p in egress.get("ports", []) or []}
            if to_monitoring and {4317, 4318} <= ports:
                found = True
    assert found, "no egress allows OTLP 4317/4318 to monitoring namespace"


# ---------------------------------------------------------------------------
# #1050/#1051 — metrics token wiring
# ---------------------------------------------------------------------------


def test_env_docker_example_declares_metrics_token():
    assert "METRICS_TOKEN" in _read(_DEPLOY / ".env.docker.example")


def test_api_deployment_injects_metrics_token_from_secret():
    env = yaml.safe_load(_read(_DEPLOY / "k8s" / "api-deployment.yaml"))["spec"]["template"]["spec"]["containers"][0][
        "env"
    ]
    entries = [e for e in env if e.get("name") == "METRICS_TOKEN"]
    assert entries, "api-deployment.yaml must define METRICS_TOKEN env"
    ref = entries[0].get("valueFrom", {}).get("secretKeyRef", {})
    assert ref.get("name"), "METRICS_TOKEN must come from a Secret reference"
    assert ref.get("key") == "METRICS_TOKEN"


# ---------------------------------------------------------------------------
# #1051 — kustomization + file inventory
# ---------------------------------------------------------------------------


def test_kustomization_lists_observability_and_drops_configmap():
    kust = yaml.safe_load(_read(_DEPLOY / "k8s" / "kustomization.yaml"))
    resources = kust["resources"]
    assert "observability/vm-agent.yaml" in resources
    assert "observability/kri-prometheusrule.yaml" in resources
    assert "observability/grafana-dashboard.yaml" in resources
    assert "observability/grafana-datasource.yaml" in resources
    assert not any(r.endswith("configmap.yaml") for r in resources)
    assert not (_DEPLOY / "k8s" / "configmap.yaml").exists()
    assert not (_DEPLOY / "k8s" / "observability" / "service-monitor.yaml").exists()


# ---------------------------------------------------------------------------
# #1051 — VictoriaMetrics stack
# ---------------------------------------------------------------------------


def test_vmagent_scrape_config_replaces_prometheus_examples():
    assert (_DEPLOY / "monitoring" / "prometheus-scrape-examples.yml").exists() is False
    raw = _read(_DEPLOY / "monitoring" / "vmagent-scrape.yml")
    doc = yaml.safe_load(raw)
    jobs = doc["scrape_configs"]
    kri_jobs = [j for j in jobs if "/metrics" in str(j.get("metrics_path", ""))]
    assert kri_jobs, "vmagent-scrape.yml must target /metrics"
    assert "bearer_token" in raw or "authorization" in raw
    assert "${METRICS_TOKEN}" in raw or "$METRICS_TOKEN" in raw


def test_monitoring_compose_stack_pinned_vm_1150():
    doc = yaml.safe_load(_read(_DEPLOY / "monitoring" / "docker-compose.monitoring.yml"))
    services = doc["services"]
    for name in ("victoria-metrics", "vmagent", "vmalert"):
        assert name in services, f"missing service: {name}"
        image = services[name]["image"]
        assert image.startswith("victoriametrics/")
        assert image.endswith(":v1.150.0"), f"unpinned image: {image}"
        assert services[name]["restart"] == "unless-stopped"
    vm_args = " ".join(services["victoria-metrics"].get("command", []))
    assert "-retentionPeriod=90d" in vm_args
    vmagent_args = " ".join(services["vmagent"].get("command", []))
    assert "-promscrape.config=/etc/vmagent/scrape.yml" in vmagent_args
    assert "-remoteWrite.url=http://victoriametrics:8428/api/v1/write" in vmagent_args
    vmalert_args = " ".join(services["vmalert"].get("command", []))
    assert "-datasource.url=http://victoriametrics:8428" in vmalert_args
    assert "-rule=/etc/vmalert/*.yml" in vmalert_args
    mounts = " ".join(services["vmalert"].get("volumes", []))
    assert "rules/kri-alerts.rules.yml" in mounts


def test_vm_agent_manifest_replaces_servicemonitor():
    docs = [d for d in yaml.safe_load_all(_read(_DEPLOY / "k8s" / "observability" / "vm-agent.yaml")) if d]
    kinds = [d["kind"] for d in docs]
    assert "Deployment" in kinds
    assert "ConfigMap" in kinds
    assert "Service" in kinds
    cm = next(d for d in docs if d["kind"] == "ConfigMap")
    cm_raw = "".join(cm["data"].values())
    assert "kri-api:8000" in cm_raw
    assert "authorization" in cm_raw or "bearer_token" in cm_raw
    svc = next(d for d in docs if d["kind"] == "Service")
    ports = [p.get("port") for p in svc["spec"]["ports"]]
    assert 8429 in ports, "vmagent Service must expose its self-metrics port 8429"


def test_grafana_datasource_points_at_victoriametrics():
    doc = yaml.safe_load(_read(_DEPLOY / "k8s" / "observability" / "grafana-datasource.yaml"))
    ds_yaml = doc["data"]["kri-datasource.yaml"]
    parsed = yaml.safe_load(ds_yaml)["datasources"][0]
    assert parsed["url"] == "http://victoriametrics.monitoring.svc:8428"
    assert parsed["type"] == "prometheus"
    assert parsed["name"] == "KRI-VictoriaMetrics"


def test_root_readme_tech_stack_row_mentions_victoriametrics():
    readme = _read(_REPO_ROOT / "README.md")
    row = next(line for line in readme.splitlines() if "**Observability**" in line)
    assert "VictoriaMetrics" in row
    assert "Prometheus," not in row
