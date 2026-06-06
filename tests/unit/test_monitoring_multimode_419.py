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
SCRAPES = ROOT / "deploy/monitoring/prometheus-scrape-examples.yml"


def _alerts(groups):
    return {r["alert"]: r["expr"] for g in groups for r in g.get("rules", []) if "alert" in r}


def test_all_artifacts_exist():
    for p in (PORTABLE, K8S_RULE, README, SCRAPES):
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


def test_servicemonitor_not_in_monitoring_namespace():
    sm = yaml.safe_load((ROOT / "deploy/k8s/observability/service-monitor.yaml").read_text())
    assert sm["metadata"]["namespace"] != "monitoring"
    assert sm["metadata"]["labels"]["release"] == "monitoring"


def test_scrape_examples_cover_compose_and_standalone():
    cfg = yaml.safe_load(SCRAPES.read_text())
    jobs = {s["job_name"] for s in cfg["scrape_configs"]}
    assert "kri-compose" in jobs and "kri-standalone" in jobs


def test_readme_documents_all_three_modes():
    txt = README.read_text().lower()
    assert "docker-compose" in txt and "kubernetes" in txt and "standalone" in txt
