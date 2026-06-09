"""
Source-contract test for issue #639:
Dead GET /{node_id}/processes endpoint removed from node_actions.py.
The UI was rewired to GET /nodes/{id}/process_stats in #613;
the old salt-dispatch route had no consumer and is now deleted.
"""

from pathlib import Path

_ROUTES_FILE = (
    Path(__file__).resolve().parents[2]
    / "fleet_platform"
    / "api"
    / "routes"
    / "node_actions.py"
)
_SOURCE = _ROUTES_FILE.read_text()


def test_list_processes_function_removed():
    assert "def list_processes" not in _SOURCE, (
        "list_processes must be removed from node_actions.py (#639)"
    )


def test_processes_route_decorator_removed():
    assert '/{node_id}/processes"' not in _SOURCE, (
        'GET /{node_id}/processes route decorator must be removed from node_actions.py (#639)'
    )


def test_list_services_still_present():
    assert "def list_services" in _SOURCE, (
        "list_services must NOT be removed — still used by the Services tab"
    )


def test_services_route_decorator_present():
    assert '/{node_id}/services"' in _SOURCE, (
        'GET /{node_id}/services route decorator must remain in node_actions.py'
    )
