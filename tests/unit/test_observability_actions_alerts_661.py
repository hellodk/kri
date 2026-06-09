"""
Contract tests for the observability additions introduced by issue #661:
  - Alert rules in BOTH rule files (portable YAML + k8s PrometheusRule CR)
  - Grafana dashboard ConfigMap (separate actions dashboard)
  - OBSERVABILITY_ARCHITECTURE.md documentation

These tests assert presence and correctness of names/expressions — they do NOT
depend on any running service or database.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

# ---------------------------------------------------------------------------
# Paths — always relative to this file so they work wherever the repo lives
# ---------------------------------------------------------------------------
_REPO = Path(__file__).resolve().parents[2]

_PORTABLE_RULES = _REPO / "deploy/monitoring/rules/kri-alerts.rules.yml"
_K8S_PROMETHEUSRULE = _REPO / "deploy/k8s/observability/kri-prometheusrule.yaml"
_DASHBOARD_ACTIONS = _REPO / "deploy/k8s/observability/grafana-dashboard-actions.yaml"
_OBS_ARCH_DOC = _REPO / "docs/OBSERVABILITY_ARCHITECTURE.md"

# ---------------------------------------------------------------------------
# Expected alert names and the metrics each expr must reference
# ---------------------------------------------------------------------------
_EXPECTED_ALERTS: dict[str, str] = {
    "KriApprovalQueueDeep": "kri_pending_action_queue_depth",
    "KriNodeActionFailureRateHigh": "kri_node_action_total",
    "KriProcessStatsIngestDrops": "kri_process_stats_rows_dropped_total",
    "KriSaltDispatchErrors": "kri_salt_dispatch_total",
}

# All 5 metric names that must appear in the architecture doc
_EXPECTED_METRICS = {
    "kri_node_action_total",
    "kri_pending_action_queue_depth",
    "kri_process_stats_rows_ingested_total",
    "kri_process_stats_rows_dropped_total",
    "kri_salt_dispatch_total",
}

# All 4 alert names that must appear in the architecture doc
_EXPECTED_ALERT_NAMES_IN_DOC = set(_EXPECTED_ALERTS.keys())

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_yaml(path: Path) -> Any:
    """Load a YAML file and return the parsed object (or list of docs)."""
    with path.open() as fh:
        docs = list(yaml.safe_load_all(fh))
    # Return the single doc for single-document files, list otherwise
    return docs[0] if len(docs) == 1 else docs


def _extract_alert_map(path: Path) -> dict[str, str]:
    """
    Return {alert_name: expr_string} for every alert rule found in a YAML
    file that is either:
      - a portable rules file  (top-level key ``groups``)
      - a k8s PrometheusRule CR (``spec.groups``)
    """
    doc = _load_yaml(path)

    # Determine where the groups live
    if "spec" in doc:
        # k8s PrometheusRule CR
        groups = doc["spec"]["groups"]
    else:
        # portable rules file
        groups = doc["groups"]

    result: dict[str, str] = {}
    for group in groups:
        for rule in group.get("rules", []):
            if "alert" in rule:
                result[rule["alert"]] = str(rule.get("expr", ""))
    return result


# ---------------------------------------------------------------------------
# YAML validity — both rule files must parse without error
# ---------------------------------------------------------------------------


def test_portable_rules_is_valid_yaml() -> None:
    assert _PORTABLE_RULES.exists(), f"Missing: {_PORTABLE_RULES}"
    data = _load_yaml(_PORTABLE_RULES)
    assert data is not None, "Portable rules file parsed as None"
    assert "groups" in data, "Portable rules file must have top-level 'groups' key"


def test_k8s_prometheusrule_is_valid_yaml() -> None:
    assert _K8S_PROMETHEUSRULE.exists(), f"Missing: {_K8S_PROMETHEUSRULE}"
    data = _load_yaml(_K8S_PROMETHEUSRULE)
    assert data is not None, "k8s PrometheusRule parsed as None"
    assert data.get("kind") == "PrometheusRule", "k8s file must have kind: PrometheusRule"
    assert "spec" in data and "groups" in data["spec"]


def test_dashboard_actions_is_valid_yaml() -> None:
    assert _DASHBOARD_ACTIONS.exists(), f"Missing: {_DASHBOARD_ACTIONS}"
    data = _load_yaml(_DASHBOARD_ACTIONS)
    assert data is not None, "Dashboard actions ConfigMap parsed as None"
    assert data.get("kind") == "ConfigMap", "Dashboard file must be kind: ConfigMap"


# ---------------------------------------------------------------------------
# Alert presence — all 4 new alerts must be in EACH rule file
# ---------------------------------------------------------------------------


def test_all_new_alerts_in_portable_rules() -> None:
    alert_map = _extract_alert_map(_PORTABLE_RULES)
    for name in _EXPECTED_ALERTS:
        assert name in alert_map, f"Alert '{name}' not found in {_PORTABLE_RULES.name}. Found: {sorted(alert_map)}"


def test_all_new_alerts_in_k8s_prometheusrule() -> None:
    alert_map = _extract_alert_map(_K8S_PROMETHEUSRULE)
    for name in _EXPECTED_ALERTS:
        assert name in alert_map, f"Alert '{name}' not found in {_K8S_PROMETHEUSRULE.name}. Found: {sorted(alert_map)}"


# ---------------------------------------------------------------------------
# Expr correctness — each alert expr must reference the right metric
# ---------------------------------------------------------------------------


def test_alert_exprs_reference_correct_metrics_portable() -> None:
    alert_map = _extract_alert_map(_PORTABLE_RULES)
    for name, metric in _EXPECTED_ALERTS.items():
        expr = alert_map.get(name, "")
        assert metric in expr, (
            f"Alert '{name}' in {_PORTABLE_RULES.name}: expected metric '{metric}' in expr but got: {expr!r}"
        )


def test_alert_exprs_reference_correct_metrics_k8s() -> None:
    alert_map = _extract_alert_map(_K8S_PROMETHEUSRULE)
    for name, metric in _EXPECTED_ALERTS.items():
        expr = alert_map.get(name, "")
        assert metric in expr, (
            f"Alert '{name}' in {_K8S_PROMETHEUSRULE.name}: expected metric '{metric}' in expr but got: {expr!r}"
        )


# ---------------------------------------------------------------------------
# Dashboard — new metrics referenced in the actions ConfigMap
# ---------------------------------------------------------------------------


def test_dashboard_actions_references_node_action_total() -> None:
    text = _DASHBOARD_ACTIONS.read_text()
    assert "kri_node_action_total" in text, "grafana-dashboard-actions.yaml must reference kri_node_action_total"


def test_dashboard_actions_references_pending_queue_depth() -> None:
    text = _DASHBOARD_ACTIONS.read_text()
    assert "kri_pending_action_queue_depth" in text


def test_dashboard_actions_references_rows_ingested_total() -> None:
    text = _DASHBOARD_ACTIONS.read_text()
    assert "kri_process_stats_rows_ingested_total" in text


def test_dashboard_actions_references_rows_dropped_total() -> None:
    text = _DASHBOARD_ACTIONS.read_text()
    assert "kri_process_stats_rows_dropped_total" in text


def test_dashboard_actions_references_salt_dispatch_total() -> None:
    text = _DASHBOARD_ACTIONS.read_text()
    assert "kri_salt_dispatch_total" in text


def test_dashboard_actions_has_grafana_dashboard_label() -> None:
    data = _load_yaml(_DASHBOARD_ACTIONS)
    labels = data.get("metadata", {}).get("labels", {})
    assert labels.get("grafana_dashboard") == "1", "ConfigMap must carry label grafana_dashboard: '1'"


# ---------------------------------------------------------------------------
# Architecture doc — all 5 metrics + 4 alert names must appear
# ---------------------------------------------------------------------------


def test_obs_arch_doc_exists() -> None:
    assert _OBS_ARCH_DOC.exists(), f"Missing: {_OBS_ARCH_DOC}"


def test_obs_arch_doc_mentions_all_metrics() -> None:
    text = _OBS_ARCH_DOC.read_text()
    for metric in _EXPECTED_METRICS:
        assert metric in text, f"OBSERVABILITY_ARCHITECTURE.md does not mention metric '{metric}'"


def test_obs_arch_doc_mentions_all_alert_names() -> None:
    text = _OBS_ARCH_DOC.read_text()
    for alert_name in _EXPECTED_ALERT_NAMES_IN_DOC:
        assert alert_name in text, f"OBSERVABILITY_ARCHITECTURE.md does not mention alert '{alert_name}'"


# ---------------------------------------------------------------------------
# Mirror check — same alert names appear in both rule files
# ---------------------------------------------------------------------------


def test_alert_names_mirrored_between_both_files() -> None:
    portable_alerts = set(_extract_alert_map(_PORTABLE_RULES))
    k8s_alerts = set(_extract_alert_map(_K8S_PROMETHEUSRULE))
    only_in_portable = portable_alerts - k8s_alerts
    only_in_k8s = k8s_alerts - portable_alerts
    assert not only_in_portable, f"Alerts only in portable rules (not in k8s CR): {only_in_portable}"
    assert not only_in_k8s, f"Alerts only in k8s CR (not in portable rules): {only_in_k8s}"
