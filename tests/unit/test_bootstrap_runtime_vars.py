"""Tests for #830 — runtime node_exporter/minion vars in bootstrap request.

TDD: these tests are written FIRST (red) and then the implementation makes them green.

Covers:
- BootstrapRequest schema: new optional fields accepted/validated
- listen_address format validation (^[\\w.\\-]*:\\d{1,5}$)
- node_exporter_version format validation (^\\d+\\.\\d+\\.\\d+$)
- Provided overrides forwarded through queue_node_bootstrap → celery task
"""

import pytest
from pydantic import ValidationError

# ── 1. Schema field validation ─────────────────────────────────────────────────


def test_bootstrap_request_accepts_no_new_fields():
    """Existing callers with no new fields must continue to work (back-compat)."""
    from fleet_platform.schemas.ansible import BootstrapRequest

    req = BootstrapRequest(minion_id="mm1", target_ip="10.0.0.1")
    assert req.node_exporter_version is None
    assert req.node_exporter_listen_address is None
    assert req.node_exporter_url_override is None


def test_bootstrap_request_accepts_valid_version():
    """node_exporter_version must match ^\\d+\\.\\d+\\.\\d+$."""
    from fleet_platform.schemas.ansible import BootstrapRequest

    req = BootstrapRequest(minion_id="mm1", target_ip="10.0.0.1", node_exporter_version="1.8.2")
    assert req.node_exporter_version == "1.8.2"


def test_bootstrap_request_accepts_valid_version_multidigit():
    from fleet_platform.schemas.ansible import BootstrapRequest

    req = BootstrapRequest(minion_id="mm1", target_ip="10.0.0.1", node_exporter_version="10.23.456")
    assert req.node_exporter_version == "10.23.456"


def test_bootstrap_request_rejects_version_with_v_prefix():
    """v1.8.2 is not semver-bare — reject it."""
    from fleet_platform.schemas.ansible import BootstrapRequest

    with pytest.raises(ValidationError, match="node_exporter_version"):
        BootstrapRequest(minion_id="mm1", target_ip="10.0.0.1", node_exporter_version="v1.8.2")


def test_bootstrap_request_rejects_partial_version():
    """1.8 (only two parts) is invalid."""
    from fleet_platform.schemas.ansible import BootstrapRequest

    with pytest.raises(ValidationError, match="node_exporter_version"):
        BootstrapRequest(minion_id="mm1", target_ip="10.0.0.1", node_exporter_version="1.8")


def test_bootstrap_request_rejects_non_numeric_version():
    from fleet_platform.schemas.ansible import BootstrapRequest

    with pytest.raises(ValidationError, match="node_exporter_version"):
        BootstrapRequest(minion_id="mm1", target_ip="10.0.0.1", node_exporter_version="latest")


def test_bootstrap_request_accepts_bare_port_listen_address():
    """:9100 (no host prefix) must be valid."""
    from fleet_platform.schemas.ansible import BootstrapRequest

    req = BootstrapRequest(minion_id="mm1", target_ip="10.0.0.1", node_exporter_listen_address=":9100")
    assert req.node_exporter_listen_address == ":9100"


def test_bootstrap_request_accepts_full_listen_address():
    """0.0.0.0:9100 must be valid."""
    from fleet_platform.schemas.ansible import BootstrapRequest

    req = BootstrapRequest(minion_id="mm1", target_ip="10.0.0.1", node_exporter_listen_address="0.0.0.0:9100")
    assert req.node_exporter_listen_address == "0.0.0.0:9100"


def test_bootstrap_request_accepts_hostname_listen_address():
    """localhost:9200 must be valid."""
    from fleet_platform.schemas.ansible import BootstrapRequest

    req = BootstrapRequest(minion_id="mm1", target_ip="10.0.0.1", node_exporter_listen_address="localhost:9200")
    assert req.node_exporter_listen_address == "localhost:9200"


def test_bootstrap_request_rejects_listen_address_no_port():
    """9100 (no colon) is invalid."""
    from fleet_platform.schemas.ansible import BootstrapRequest

    with pytest.raises(ValidationError, match="node_exporter_listen_address"):
        BootstrapRequest(minion_id="mm1", target_ip="10.0.0.1", node_exporter_listen_address="9100")


def test_bootstrap_request_rejects_listen_address_colon_only():
    """: (no port) is invalid."""
    from fleet_platform.schemas.ansible import BootstrapRequest

    with pytest.raises(ValidationError, match="node_exporter_listen_address"):
        BootstrapRequest(minion_id="mm1", target_ip="10.0.0.1", node_exporter_listen_address=":")


def test_bootstrap_request_rejects_listen_address_non_numeric_port():
    """:http is invalid — port must be numeric."""
    from fleet_platform.schemas.ansible import BootstrapRequest

    with pytest.raises(ValidationError, match="node_exporter_listen_address"):
        BootstrapRequest(minion_id="mm1", target_ip="10.0.0.1", node_exporter_listen_address=":http")


def test_bootstrap_request_ignores_removed_bootstrap_full_field():
    """bootstrap_full was removed (unified bootstrap); extra fields are ignored."""
    from fleet_platform.schemas.ansible import BootstrapRequest

    req = BootstrapRequest(minion_id="mm1", target_ip="10.0.0.1", bootstrap_full=True)  # type: ignore[call-arg]
    assert not hasattr(req, "bootstrap_full")


def test_bootstrap_request_accepts_url_override():
    from fleet_platform.schemas.ansible import BootstrapRequest

    req = BootstrapRequest(
        minion_id="mm1",
        target_ip="10.0.0.1",
        node_exporter_url_override="https://mirror.example.com/node_exporter.tar.gz",
    )
    assert req.node_exporter_url_override == "https://mirror.example.com/node_exporter.tar.gz"


# ── 2. queue_node_bootstrap forwards new params to celery task ─────────────────


def test_queue_node_bootstrap_signature_accepts_runtime_vars():
    """queue_node_bootstrap signature accepts all four new optional runtime params."""
    from pathlib import Path

    src = Path("fleet_platform/services/bootstrap_svc.py").read_text()

    assert "node_exporter_version" in src
    assert "node_exporter_listen_address" in src
    assert "node_exporter_url_override" in src
    # bootstrap_full was removed in the unified-bootstrap change
    assert "bootstrap_full" not in src


def test_queue_node_bootstrap_forwards_vars_to_delay():
    """queue_node_bootstrap passes runtime vars to bootstrap_node.delay()."""
    from pathlib import Path

    src = Path("fleet_platform/services/bootstrap_svc.py").read_text()

    # Each new var must appear in a .delay(...) call (forwarded as kwarg)
    assert "node_exporter_version=node_exporter_version" in src
    assert "node_exporter_listen_address=node_exporter_listen_address" in src
    assert "node_exporter_url_override=node_exporter_url_override" in src


# ── 3. bootstrap_node celery task merges runtime vars into extravars ───────────


def test_bootstrap_node_extravars_include_runtime_overrides():
    """bootstrap_node builds runtime_extravars and merges them into ansible-runner extravars.

    Uses source-code inspection (consistent with the project's existing test style for
    ansible_tasks.py — ansible_runner is not installed in the unit-test environment).
    """
    from pathlib import Path

    src = Path("fleet_platform/workers/ansible_tasks.py").read_text()

    # The task must define a runtime_extravars dict
    assert "runtime_extravars" in src, "bootstrap_node must define runtime_extravars dict"

    # Each new override key must be conditionally inserted
    assert "node_exporter_version" in src
    assert "node_exporter_listen_address" in src
    assert "node_exporter_url_override" in src

    # runtime_extravars must be spread into the final extravars dict passed to ansible-runner
    assert "**runtime_extravars" in src, "runtime_extravars must be unpacked into extravars"

    # The task signature must accept all four new params
    import re

    sig_match = re.search(
        r"def bootstrap_node\(.*?\) -> dict",
        src,
        re.DOTALL,
    )
    assert sig_match, "bootstrap_node signature not found"
    sig = sig_match.group(0)
    assert "node_exporter_version" in sig
    assert "node_exporter_listen_address" in sig
    assert "node_exporter_url_override" in sig
    # bootstrap_full was removed in the unified-bootstrap change
    assert "bootstrap_full" not in sig


# ── 4. bootstrap_node injects OTLP push settings into extravars (#968) ─────────


def test_bootstrap_node_wires_otlp_settings_into_extravars():
    """OTLP push settings (from PlatformSettings) are read while the db session is
    open and conditionally merged into runtime_extravars, so the otel_collector
    role targets the operator-configured endpoint. Source-inspection style,
    consistent with the node_exporter runtime-override tests above.
    """
    from pathlib import Path

    src = Path("fleet_platform/workers/ansible_tasks.py").read_text()

    # Read all three OTLP settings from PlatformSettings.
    assert "get_setting_sync(db, \"otlp_endpoint\")" in src
    assert "get_setting_sync(db, \"otlp_protocol\")" in src
    assert "get_setting_sync(db, \"otlp_headers\")" in src

    # Conditionally inject into runtime_extravars (omitted when unset → role defaults).
    assert 'runtime_extravars["otlp_endpoint"]' in src
    assert 'runtime_extravars["otlp_protocol"]' in src
    assert 'runtime_extravars["otlp_headers"]' in src
