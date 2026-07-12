"""OTEL Phase 3 — the redundant Deploy Monitoring path is removed.

Bootstrap Play 1 now always installs node monitoring (node_exporter +
otel_collector) independent of Salt (#967/#968), so the standalone
deploy_node_exporter.yml playbook and the "Deploy Monitoring" button are dead.

Paths resolved via pathlib from this file (never absolute).
"""

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PLAYBOOKS = _REPO_ROOT / "playbooks"
_FRONTEND = _REPO_ROOT / "frontend" / "src"


def test_deploy_node_exporter_playbook_removed():
    assert not (_PLAYBOOKS / "deploy_node_exporter.yml").exists(), (
        "deploy_node_exporter.yml is redundant — bootstrap Play 1 installs monitoring."
    )


def test_overview_tab_has_no_deploy_monitoring_button():
    overview = (_FRONTEND / "pages" / "nodeDetail" / "OverviewTab.tsx").read_text()
    assert "Deploy Monitoring" not in overview
    assert "deploy_node_exporter.yml" not in overview
    assert "deployNodeExporter" not in overview
