"""Contract tests for the otel_collector role (#968 — Phase 2 of the node-otel
metrics-push design, docs/superpowers/specs/2026-07-12-node-otel-metrics-push-design.md).

The role installs otelcol-contrib configured with a prometheus receiver scraping
the local node_exporter (127.0.0.1:9100) and an OTLP exporter pushing to a
configurable endpoint. It mirrors playbooks/roles/node_exporter in structure and
must have no dependency on the `common` role (it runs in bootstrap_node.yml's
Play 1, which is decoupled from Salt and must not short-circuit early).

All paths are relative to the repository root, resolved via pathlib from this
file's location (never absolute), so the test works regardless of cwd.
"""

from pathlib import Path

import jinja2
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
ROLE_DIR = REPO_ROOT / "playbooks" / "roles" / "otel_collector"
TASKS_MAIN = ROLE_DIR / "tasks" / "main.yml"
DEFAULTS_MAIN = ROLE_DIR / "defaults" / "main.yml"
META_MAIN = ROLE_DIR / "meta" / "main.yml"
CONFIG_TEMPLATE = ROLE_DIR / "templates" / "otelcol-config.yaml.j2"
BOOTSTRAP_PLAYBOOK = REPO_ROOT / "playbooks" / "bootstrap_node.yml"


def _role_yaml_files() -> list[Path]:
    return sorted(ROLE_DIR.rglob("*.yml"))


def _render_config(otlp_protocol: str, otlp_endpoint: str, otlp_headers: str = "") -> dict:
    tpl = CONFIG_TEMPLATE.read_text()
    rendered = jinja2.Environment().from_string(tpl).render(
        otlp_protocol=otlp_protocol,
        otlp_endpoint=otlp_endpoint,
        otlp_headers=otlp_headers,
    )
    return yaml.safe_load(rendered)


# ── role directory / required files ─────────────────────────────────────────


def test_role_directory_exists():
    assert ROLE_DIR.is_dir(), f"{ROLE_DIR} must exist"


def test_required_role_files_exist():
    for rel in (
        "tasks/main.yml",
        "tasks/install.yml",
        "tasks/service_launchd.yml",
        "tasks/service_systemd.yml",
        "defaults/main.yml",
        "handlers/main.yml",
        "meta/main.yml",
        "templates/otelcol-config.yaml.j2",
        "templates/com.otelcol.contrib.plist.j2",
        "templates/otelcol.service.j2",
    ):
        assert (ROLE_DIR / rel).is_file(), f"{rel} must exist"


# ── config template renders a valid prometheus receiver + OTLP exporter ─────


def test_config_template_renders_prometheus_receiver_targeting_node_exporter():
    parsed = _render_config(otlp_protocol="http", otlp_endpoint="http://100.89.50.27:30318")
    scrape_configs = parsed["receivers"]["prometheus"]["config"]["scrape_configs"]
    targets = scrape_configs[0]["static_configs"][0]["targets"]
    assert targets == ["127.0.0.1:9100"]


def test_config_template_http_protocol_uses_otlphttp_exporter():
    parsed = _render_config(otlp_protocol="http", otlp_endpoint="http://100.89.50.27:30318")
    assert "otlphttp" in parsed["exporters"]
    assert parsed["exporters"]["otlphttp"]["endpoint"] == "http://100.89.50.27:30318"
    assert parsed["service"]["pipelines"]["metrics"]["receivers"] == ["prometheus"]
    assert parsed["service"]["pipelines"]["metrics"]["exporters"] == ["otlphttp"]


def test_config_template_grpc_protocol_uses_otlp_exporter():
    parsed = _render_config(otlp_protocol="grpc", otlp_endpoint="http://100.89.50.27:30317")
    assert "otlp" in parsed["exporters"]
    assert parsed["exporters"]["otlp"]["endpoint"] == "http://100.89.50.27:30317"
    assert parsed["service"]["pipelines"]["metrics"]["exporters"] == ["otlp"]


def test_config_template_optional_headers_render_as_valid_yaml():
    parsed = _render_config(
        otlp_protocol="http",
        otlp_endpoint="http://100.89.50.27:30318",
        otlp_headers="Authorization: Bearer testtoken",
    )
    assert parsed["exporters"]["otlphttp"]["headers"] == {"Authorization": "Bearer testtoken"}


def test_config_template_no_headers_key_when_headers_empty():
    parsed = _render_config(otlp_protocol="http", otlp_endpoint="http://100.89.50.27:30318")
    assert "headers" not in parsed["exporters"]["otlphttp"]


# ── defaults declare the required vars ───────────────────────────────────────


def test_defaults_declare_required_vars():
    defaults = DEFAULTS_MAIN.read_text()
    assert "otel_collector_version" in defaults
    assert "otlp_endpoint" in defaults
    assert "otlp_protocol" in defaults


def test_defaults_load_as_valid_yaml_with_expected_values():
    defaults = yaml.safe_load(DEFAULTS_MAIN.read_text())
    assert "otel_collector_version" in defaults
    assert defaults["otlp_protocol"] == "http"
    assert defaults["otlp_endpoint"].startswith("http://")


# ── tasks derive arch themselves — no `common` role dependency ──────────────


def test_tasks_derive_os_arch_without_common_role():
    main_yml = TASKS_MAIN.read_text()
    assert "ansible_architecture" in main_yml
    assert "set_fact" in main_yml
    assert "otel_arch" in main_yml
    assert "otel_os" in main_yml
    # No dependency on the `common` role — this role runs in bootstrap Play 1.
    assert "import_role" not in main_yml
    assert "name: common" not in main_yml


def test_meta_has_no_dependency_on_common_role():
    meta = yaml.safe_load(META_MAIN.read_text())
    assert meta.get("dependencies") == []


# ── FQCN throughout, no community.general anywhere in the role ──────────────


def test_all_module_references_are_fqcn():
    """Every ansible.builtin task module must use the fully-qualified name."""
    bare_module_markers = (
        "- template:",
        "- shell:",
        "- command:",
        "- file:",
        "- get_url:",
        "- systemd:",
        "- set_fact:",
        "- include_tasks:",
    )
    offenders = []
    for path in _role_yaml_files():
        content = path.read_text()
        for marker in bare_module_markers:
            if marker in content:
                offenders.append(f"{path.relative_to(REPO_ROOT)}: {marker}")
    assert not offenders, f"non-FQCN module usage found: {offenders}"


def test_no_community_general_in_role():
    offenders = []
    for path in _role_yaml_files():
        if "community.general" in path.read_text():
            offenders.append(str(path.relative_to(REPO_ROOT)))
    assert not offenders, f"community.general referenced in: {offenders}"


# ── service tasks use started, not forced restarted ─────────────────────────


def test_service_tasks_use_started_not_forced_restarted():
    for name in ("service_systemd.yml", "service_launchd.yml"):
        path = ROLE_DIR / "tasks" / name
        content = path.read_text()
        assert "state: restarted" not in content, f"{name} must not force state: restarted"


# ── wired into bootstrap_node.yml Play 1 (Salt-independent) ─────────────────


def test_otel_collector_wired_into_bootstrap_monitoring_play():
    plays = yaml.safe_load(BOOTSTRAP_PLAYBOOK.read_text())
    monitoring_play = None
    for play in plays:
        role_names = [r if isinstance(r, str) else r.get("role", r.get("name")) for r in play.get("roles", [])]
        if "node_exporter" in role_names:
            monitoring_play = role_names
            break
    assert monitoring_play is not None, "no play runs node_exporter"
    assert monitoring_play == ["node_exporter", "otel_collector"]
