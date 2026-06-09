"""Rate limiting tests for node action endpoints (issue #616)."""

import re
from pathlib import Path


def test_rate_limiter_imported():
    """Verify SlowAPI limiter is imported in node_actions module."""
    from fleet_platform.api.limiter import limiter

    assert limiter is not None, "limiter must be importable from fleet_platform.api.limiter"


def test_node_actions_module_imports():
    """Verify the node_actions module imports Request and limiter without errors."""
    import fleet_platform.api.routes.node_actions

    assert hasattr(fleet_platform.api.routes.node_actions, "Request"), "Request must be imported"
    assert hasattr(fleet_platform.api.routes.node_actions, "limiter"), "limiter must be imported"


def test_node_actions_source_has_rate_limit_decorators():
    """Verify the three endpoints are decorated with @limiter.limit directives."""
    source_path = Path(__file__).parent.parent.parent / "fleet_platform" / "api" / "routes" / "node_actions.py"
    source = source_path.read_text()

    # Check for both rate limit decorators (5/minute for request, 20/minute for approve/reject)
    assert '@limiter.limit("5/minute")' in source, "request_node_action must have @limiter.limit('5/minute')"
    assert source.count('@limiter.limit("20/minute")') >= 2, (
        "approve_action and reject_action must each have @limiter.limit('20/minute')"
    )


def test_node_actions_source_has_request_parameter():
    """Verify all three endpoints have 'request: Request' as first parameter."""
    source_path = Path(__file__).parent.parent.parent / "fleet_platform" / "api" / "routes" / "node_actions.py"
    source = source_path.read_text()

    # Count occurrences of "request: Request," pattern (tolerant of whitespace)
    matches = re.findall(r"request\s*:\s*Request", source)
    assert len(matches) >= 3, (
        f"Expected at least 3 occurrences of 'request: Request' in function signatures, found {len(matches)}"
    )


def test_fastapi_request_imported():
    """Verify Request is imported from fastapi."""
    from fleet_platform.api.routes.node_actions import Request

    assert Request is not None, "Request must be importable from node_actions"


def test_module_syntax_valid():
    """Verify the module can be imported without syntax or decorator errors."""
    import fleet_platform.api.routes.node_actions

    # If the module imports without error, decorators are syntactically valid
    assert hasattr(fleet_platform.api.routes.node_actions, "request_node_action")
    assert hasattr(fleet_platform.api.routes.node_actions, "approve_action")
    assert hasattr(fleet_platform.api.routes.node_actions, "reject_action")
