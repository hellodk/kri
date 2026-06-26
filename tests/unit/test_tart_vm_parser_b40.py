"""Tests for #47: tart VM output parser."""

from pathlib import Path


def test_parse_empty_output():
    from fleet_platform.api.routes.nodes import _parse_tart_output

    assert _parse_tart_output("") == []


def test_parse_tart_not_found():
    from fleet_platform.api.routes.nodes import _parse_tart_output

    assert _parse_tart_output("tart_not_found") == []


def test_parse_json_output():
    import json

    from fleet_platform.api.routes.nodes import _parse_tart_output

    data = [{"name": "test-vm", "state": "Running", "cpu": 4, "memory": 8192, "source": "ghcr.io/test"}]
    result = _parse_tart_output(json.dumps(data))
    assert len(result) == 1
    assert result[0]["name"] == "test-vm"
    assert result[0]["state"] == "Running"
    assert result[0]["cpu"] == 4


def test_parse_json_multiple_vms():
    import json

    from fleet_platform.api.routes.nodes import _parse_tart_output

    data = [
        {"name": "vm1", "state": "Running", "cpu": 2, "memory": 4096, "source": "local"},
        {"name": "vm2", "state": "Stopped", "cpu": 4, "memory": 8192, "source": "local"},
    ]
    result = _parse_tart_output(json.dumps(data))
    assert len(result) == 2
    assert result[1]["state"] == "Stopped"


def test_parse_plain_text_fallback():
    from fleet_platform.api.routes.nodes import _parse_tart_output

    output = "Name    Source    State\ntest-vm    local    Running"
    result = _parse_tart_output(output)
    assert len(result) == 1
    assert result[0]["name"] == "test-vm"


def test_parse_invalid_json_falls_back():
    from fleet_platform.api.routes.nodes import _parse_tart_output

    result = _parse_tart_output("{not valid json")
    # Should not raise — falls back to plain text parsing
    assert isinstance(result, list)


def test_vms_endpoint_in_nodes_route():
    from fleet_platform.api.routes import nodes

    assert hasattr(nodes, "list_node_vms"), "nodes route module must expose a list_node_vms endpoint handler (#47)"


def test_vms_api_in_frontend():
    # Frontend-only artifact: TypeScript is non-importable from Python unit tests.
    api = (Path(__file__).parent.parent.parent / "frontend/src/api/vms.ts").read_text()
    assert "listNodeVMs" in api
    assert "TartVM" in api
