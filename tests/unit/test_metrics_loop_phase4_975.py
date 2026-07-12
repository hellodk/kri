"""Contract tests for #975 — close the node-metrics loop (OTEL monitoring Phase 4).

Problem: kri queried Prometheus with a raw `instance="<ip>:9100"` label selector,
but that label is renamed/clobbered when Prometheus scrapes the otel-gateway's
prometheus exporter (which re-exposes metrics pushed via OTLP from the Mac
nodes' otelcol-contrib). The fix is a stable resource attribute,
`fleet_instance`, stamped by the otelcol `resource/fleet` processor and turned
into a Prometheus label by the gateway's `resource_to_telemetry_conversion`
(Prometheus's own scrape of the gateway only manages `instance`/`job`, so this
label survives). kri now queries by `fleet_instance` instead of `instance`.

All paths are resolved via pathlib from this file's location (never
absolute), so the test works regardless of cwd.
"""

from pathlib import Path

import jinja2
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
ROLE_DIR = REPO_ROOT / "playbooks" / "roles" / "otel_collector"
CONFIG_TEMPLATE = ROLE_DIR / "templates" / "otelcol-config.yaml.j2"
DEFAULTS_MAIN = ROLE_DIR / "defaults" / "main.yml"
NODE_ACTIONS_SRC = REPO_ROOT / "fleet_platform" / "api" / "routes" / "node_actions.py"


def _render_config(otlp_protocol: str, otlp_endpoint: str, otlp_headers: str = "", **extra) -> dict:
    tpl = CONFIG_TEMPLATE.read_text()
    rendered = jinja2.Environment().from_string(tpl).render(
        otlp_protocol=otlp_protocol,
        otlp_endpoint=otlp_endpoint,
        otlp_headers=otlp_headers,
        **extra,
    )
    return yaml.safe_load(rendered)


# ── otelcol-config.yaml.j2 stamps a stable fleet_instance resource attribute ──


def test_config_template_has_resource_fleet_processor():
    parsed = _render_config(
        otlp_protocol="http",
        otlp_endpoint="http://100.89.50.27:30318",
        minion_id="192.168.1.64",
    )
    assert "processors" in parsed
    proc = parsed["processors"]["resource/fleet"]
    attrs = proc["attributes"]
    assert len(attrs) == 1
    attr = attrs[0]
    assert attr["key"] == "fleet_instance"
    assert attr["action"] == "upsert"
    assert attr["value"] == "192.168.1.64:9100"


def test_config_template_metrics_pipeline_wires_resource_fleet_processor():
    parsed = _render_config(
        otlp_protocol="http",
        otlp_endpoint="http://100.89.50.27:30318",
        minion_id="192.168.1.64",
    )
    metrics_pipeline = parsed["service"]["pipelines"]["metrics"]
    assert metrics_pipeline["receivers"] == ["prometheus"]
    assert metrics_pipeline["processors"] == ["resource/fleet"]
    assert metrics_pipeline["exporters"] == ["otlphttp"]


def test_config_template_fleet_instance_defaults_to_minion_id_when_otel_node_instance_empty():
    parsed = _render_config(
        otlp_protocol="http",
        otlp_endpoint="http://100.89.50.27:30318",
        otel_node_instance="",
        minion_id="192.168.1.64",
    )
    attr = parsed["processors"]["resource/fleet"]["attributes"][0]
    assert attr["value"] == "192.168.1.64:9100"


def test_config_template_fleet_instance_uses_explicit_override_when_set():
    parsed = _render_config(
        otlp_protocol="http",
        otlp_endpoint="http://100.89.50.27:30318",
        otel_node_instance="override-host:9100",
        minion_id="192.168.1.64",
    )
    attr = parsed["processors"]["resource/fleet"]["attributes"][0]
    assert attr["value"] == "override-host:9100"


# ── defaults/main.yml declares otel_node_instance ─────────────────────────────


def test_defaults_declare_otel_node_instance():
    defaults = yaml.safe_load(DEFAULTS_MAIN.read_text())
    assert "otel_node_instance" in defaults
    assert defaults["otel_node_instance"] == ""
    assert "otel_node_instance" in defaults["_kri_var_descriptions"]


# ── node_actions.py queries Prometheus by fleet_instance, not bare instance ───


def test_node_actions_promql_uses_fleet_instance_label():
    src = NODE_ACTIONS_SRC.read_text()
    assert 'fleet_instance="{fleet_instance}"' in src
    # The old bare "instance=" node selector must be gone from the PromQL query
    # strings built in get_node_metrics.
    assert 'instance="{instance}"' not in src


def test_node_actions_promql_queries_all_use_fleet_instance():
    src = NODE_ACTIONS_SRC.read_text()
    start = src.index("queries = {")
    end = src.index("}", src.index("net_tx_kbs", start))
    queries_block = src[start:end]
    # Every metric query selector must key off fleet_instance.
    assert queries_block.count("fleet_instance=") >= 6
    assert "instance=" not in queries_block.replace("fleet_instance=", "")
