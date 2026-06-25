"""Tests for resource profiling tab (#293)."""


def test_metrics_route_registered():
    from fleet_platform.api.routes.node_actions import router

    paths = [r.path for r in router.routes]
    assert any("metrics" in p for p in paths), f"metrics route missing from {paths}"


def test_prometheus_url_setting_exists():
    from fleet_platform.services.platform_settings_svc import PROMETHEUS_URL

    assert PROMETHEUS_URL == "prometheus_url"


def test_resources_tab_in_nodedetal():
    # #787: ResourcesTab content lives in pages/nodeDetail/; read shell + package.
    from pathlib import Path

    _pages = Path("frontend/src/pages")
    content = "\n".join(
        [
            (_pages / "NodeDetail.tsx").read_text(),
            *(p.read_text() for p in sorted((_pages / "nodeDetail").glob("*.tsx"))),
        ]
    )
    assert "'resources'" in content or '"resources"' in content
    assert "metricsData" in content
    assert "Sparkline" in content
