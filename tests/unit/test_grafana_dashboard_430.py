"""Tests for issue #430 — kri Grafana dashboard (kri.json + ConfigMap + README)."""

import json
import pathlib

import yaml

REPO_ROOT = pathlib.Path(__file__).parent.parent.parent
DASHBOARD_JSON = REPO_ROOT / "deploy" / "monitoring" / "dashboards" / "kri.json"
CONFIGMAP_YAML = REPO_ROOT / "deploy" / "k8s" / "observability" / "grafana-dashboard.yaml"
README = REPO_ROOT / "deploy" / "monitoring" / "README.md"


# ── kri.json tests ────────────────────────────────────────────────────────────


def test_dashboard_json_is_valid_json():
    """deploy/monitoring/dashboards/kri.json must parse as valid JSON."""
    content = DASHBOARD_JSON.read_text()
    dashboard = json.loads(content)
    assert isinstance(dashboard, dict)


def test_dashboard_has_required_top_level_fields():
    """Dashboard must have title, uid, and tags fields."""
    dashboard = json.loads(DASHBOARD_JSON.read_text())
    assert dashboard.get("title") == "kri Fleet Platform"
    assert dashboard.get("uid") == "kri-fleet"
    assert "kri" in dashboard.get("tags", [])


def test_dashboard_schema_version():
    """schemaVersion must be >= 39 (Grafana 10/11)."""
    dashboard = json.loads(DASHBOARD_JSON.read_text())
    assert dashboard.get("schemaVersion", 0) >= 39


def test_dashboard_has_templated_datasource():
    """Dashboard must have a DS_PROMETHEUS datasource template variable."""
    dashboard = json.loads(DASHBOARD_JSON.read_text())
    variables = dashboard.get("templating", {}).get("list", [])
    names = [v.get("name") for v in variables]
    assert "DS_PROMETHEUS" in names
    ds_var = next(v for v in variables if v.get("name") == "DS_PROMETHEUS")
    assert ds_var.get("type") == "datasource"


def _all_targets(dashboard: dict) -> list[dict]:
    """Flatten all panel targets from a dashboard dict."""
    targets: list[dict] = []
    for panel in dashboard.get("panels", []):
        targets.extend(panel.get("targets", []))
    return targets


def test_dashboard_references_kri_node_ssh_reachable():
    """At least one panel target must reference kri_node_ssh_reachable."""
    dashboard = json.loads(DASHBOARD_JSON.read_text())
    exprs = [t.get("expr", "") for t in _all_targets(dashboard)]
    assert any("kri_node_ssh_reachable" in e for e in exprs), "No panel references kri_node_ssh_reachable"


def test_dashboard_references_http_duration_bucket():
    """At least one panel target must reference kri_http_request_duration_seconds_bucket."""
    dashboard = json.loads(DASHBOARD_JSON.read_text())
    exprs = [t.get("expr", "") for t in _all_targets(dashboard)]
    assert any("kri_http_request_duration_seconds_bucket" in e for e in exprs), (
        "No panel references kri_http_request_duration_seconds_bucket"
    )


def test_dashboard_ssh_reachable_legend_uses_minion_id():
    """SSH reachability timeseries must use {{minion_id}} as legendFormat."""
    dashboard = json.loads(DASHBOARD_JSON.read_text())
    ssh_targets = [t for t in _all_targets(dashboard) if "kri_node_ssh_reachable" in t.get("expr", "")]
    assert ssh_targets, "No target with kri_node_ssh_reachable"
    assert any("minion_id" in t.get("legendFormat", "") for t in ssh_targets), (
        "kri_node_ssh_reachable target does not use {{minion_id}} legendFormat"
    )


def test_dashboard_has_stat_panels():
    """Dashboard must contain at least one stat panel for the node overview row."""
    dashboard = json.loads(DASHBOARD_JSON.read_text())
    types = [p.get("type") for p in dashboard.get("panels", [])]
    assert "stat" in types, "No stat panel found — node overview stats missing"


def test_dashboard_has_p99_latency_panel():
    """Dashboard must have a p99 histogram_quantile expression."""
    dashboard = json.loads(DASHBOARD_JSON.read_text())
    exprs = [t.get("expr", "") for t in _all_targets(dashboard)]
    assert any("histogram_quantile(0.99" in e and "kri_http_request_duration_seconds_bucket" in e for e in exprs), (
        "No p99 histogram_quantile expression found"
    )


def test_dashboard_has_celery_panel():
    """Dashboard must reference kri_celery_tasks_total."""
    dashboard = json.loads(DASHBOARD_JSON.read_text())
    exprs = [t.get("expr", "") for t in _all_targets(dashboard)]
    assert any("kri_celery_tasks_total" in e for e in exprs), "No panel references kri_celery_tasks_total"


def test_dashboard_has_http_request_rate_panel():
    """Dashboard must reference kri_http_requests_total."""
    dashboard = json.loads(DASHBOARD_JSON.read_text())
    exprs = [t.get("expr", "") for t in _all_targets(dashboard)]
    assert any("kri_http_requests_total" in e for e in exprs), "No panel references kri_http_requests_total"


# ── ConfigMap tests ───────────────────────────────────────────────────────────


def test_configmap_yaml_is_valid():
    """deploy/k8s/observability/grafana-dashboard.yaml must parse as valid YAML."""
    content = CONFIGMAP_YAML.read_text()
    doc = yaml.safe_load(content)
    assert isinstance(doc, dict)


def test_configmap_namespace_is_kri():
    """ConfigMap must be in the kri namespace (not utilities or monitoring)."""
    doc = yaml.safe_load(CONFIGMAP_YAML.read_text())
    assert doc["metadata"]["namespace"] == "kri"


def test_configmap_has_grafana_dashboard_label():
    """ConfigMap must have label grafana_dashboard: '1'."""
    doc = yaml.safe_load(CONFIGMAP_YAML.read_text())
    labels = doc["metadata"].get("labels", {})
    assert labels.get("grafana_dashboard") == "1", f"Expected grafana_dashboard='1', got {labels}"


def test_configmap_data_key_is_kri_json():
    """ConfigMap data must have key 'kri.json'."""
    doc = yaml.safe_load(CONFIGMAP_YAML.read_text())
    assert "kri.json" in doc.get("data", {}), "ConfigMap data does not contain key 'kri.json'"


def test_configmap_embedded_json_is_valid():
    """The kri.json value inside the ConfigMap must parse as valid JSON."""
    doc = yaml.safe_load(CONFIGMAP_YAML.read_text())
    raw = doc["data"]["kri.json"]
    embedded = json.loads(raw)
    assert isinstance(embedded, dict)


def test_configmap_embedded_json_uid_matches():
    """The embedded JSON uid must be 'kri-fleet', matching the dashboard file."""
    doc = yaml.safe_load(CONFIGMAP_YAML.read_text())
    embedded = json.loads(doc["data"]["kri.json"])
    assert embedded.get("uid") == "kri-fleet"


def test_configmap_name():
    """ConfigMap name must be kri-dashboard."""
    doc = yaml.safe_load(CONFIGMAP_YAML.read_text())
    assert doc["metadata"]["name"] == "kri-dashboard"


# ── README tests ──────────────────────────────────────────────────────────────


def test_readme_contains_grafana_dashboard_section():
    """deploy/monitoring/README.md must contain a '## Grafana dashboard' section."""
    content = README.read_text()
    assert "## Grafana dashboard" in content, "README.md is missing '## Grafana dashboard' section"


def test_readme_mentions_compose_standalone_import():
    """README Grafana section must mention docker-compose / standalone import."""
    content = README.read_text()
    assert "docker-compose" in content or "standalone" in content, (
        "README does not mention docker-compose/standalone import path"
    )


def test_readme_mentions_k8s_configmap():
    """README Grafana section must mention the k8s ConfigMap apply command."""
    content = README.read_text()
    assert "grafana-dashboard.yaml" in content, "README does not mention grafana-dashboard.yaml kubectl apply"
