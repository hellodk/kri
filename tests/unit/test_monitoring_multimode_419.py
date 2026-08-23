"""#419: kri monitoring artifacts are portable across all 3 deploy modes.

Guards the invariant from deploy/monitoring/README.md: the portable rule file and
the k8s PrometheusRule wrapper must declare the SAME alert/expr, so the rule
behaves identically whether loaded via `rule_files:` (compose/standalone) or as a
PrometheusRule CR (k8s)."""

from pathlib import Path

import yaml

ROOT = Path(__file__).parent.parent.parent
PORTABLE = ROOT / "deploy/monitoring/rules/kri-alerts.rules.yml"
K8S_RULE = ROOT / "deploy/k8s/observability/kri-prometheusrule.yaml"
README = ROOT / "deploy/monitoring/README.md"
SCRAPES = ROOT / "deploy/monitoring/vmagent-scrape.yml"
VM_STACK = ROOT / "deploy/monitoring/docker-compose.monitoring.yml"


def _alerts(groups):
    return {r["alert"]: r["expr"] for g in groups for r in g.get("rules", []) if "alert" in r}


def test_all_artifacts_exist():
    for p in (PORTABLE, K8S_RULE, README, SCRAPES, VM_STACK):
        assert p.exists(), f"missing monitoring artifact: {p}"


def test_portable_and_k8s_rules_in_sync():
    portable = _alerts(yaml.safe_load(PORTABLE.read_text())["groups"])
    k8s = _alerts(yaml.safe_load(K8S_RULE.read_text())["spec"]["groups"])
    assert portable, "portable rule file has no alerts"
    assert portable == k8s, "portable rules and k8s PrometheusRule drifted — keep them in sync (#419)"


def test_k8s_rule_targets_kri_namespace_and_release_label():
    doc = yaml.safe_load(K8S_RULE.read_text())
    assert doc["metadata"]["namespace"] == "kri"
    assert doc["metadata"]["labels"]["release"] == "monitoring"


def test_vm_agent_scrapes_kri_with_metrics_token():
    """#1051: vmagent scrape config targets kri-api with METRICS_TOKEN auth (#1050)."""
    cfg = yaml.safe_load(SCRAPES.read_text())
    jobs = {s["job_name"]: s for s in cfg["scrape_configs"]}
    assert "kri-api" in jobs, f"vmagent scrape must keep job_name kri-api (alerts depend on it): {sorted(jobs)}"
    job = yaml.safe_dump(jobs["kri-api"])
    assert "authorization" in job or "bearer" in job.lower(), "kri /metrics requires METRICS_TOKEN bearer auth"


def test_vm_stack_pins_victoriametrics_images():
    txt = VM_STACK.read_text()
    for image in ("victoria-metrics:v1.150.0", "vmagent:v1.150.0", "vmalert:v1.150.0"):
        assert image in txt, f"monitoring stack must pin {image} (no :latest)"


def test_readme_documents_all_three_modes():
    txt = README.read_text().lower()
    assert "docker-compose" in txt and "kubernetes" in txt and "standalone" in txt
