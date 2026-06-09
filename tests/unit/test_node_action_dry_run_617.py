"""Tests for node action dry_run mode (issue #617)."""

from fleet_platform.api.routes.node_actions import NodeActionRequest


def test_node_action_request_dry_run_defaults_false():
    """NodeActionRequest.dry_run defaults to False."""
    req = NodeActionRequest(action_type="process_stop")
    assert req.dry_run is False


def test_node_action_request_dry_run_explicit_true():
    """NodeActionRequest.dry_run can be set to True."""
    req = NodeActionRequest(action_type="process_stop", dry_run=True)
    assert req.dry_run is True


def test_node_action_request_dry_run_explicit_false():
    """NodeActionRequest.dry_run can be explicitly set to False."""
    req = NodeActionRequest(action_type="service_stop", dry_run=False)
    assert req.dry_run is False


def test_node_action_request_with_params():
    """NodeActionRequest.dry_run works with params."""
    req = NodeActionRequest(
        action_type="process_stop",
        params={"pid": "1234"},
        dry_run=True,
    )
    assert req.dry_run is True
    assert req.params == {"pid": "1234"}


def test_node_actions_py_contains_dry_run_field():
    """fleet_platform/api/routes/node_actions.py contains dry_run: bool = False."""
    import inspect

    import fleet_platform.api.routes.node_actions as node_actions_module

    source = inspect.getsource(node_actions_module.NodeActionRequest)
    assert "dry_run: bool = False" in source


def test_node_actions_py_has_dry_run_branch():
    """fleet_platform/api/routes/node_actions.py has a dry_run response branch."""
    import inspect

    import fleet_platform.api.routes.node_actions as node_actions_module

    source = inspect.getsource(node_actions_module.request_node_action)
    assert "if payload.dry_run:" in source
    assert 'status="dry_run"' in source
    assert "No action created, no email sent" in source


def test_node_actions_py_dry_run_after_validate_and_404():
    """dry_run branch appears after _validate_action_params and node 404 check, before destructive check."""
    from pathlib import Path

    src_path = Path(__file__).resolve().parents[2] / "fleet_platform" / "api" / "routes" / "node_actions.py"
    source = src_path.read_text()

    validate_idx = source.find("_validate_action_params(")
    node_404_idx = source.find('raise HTTPException(status_code=404, detail="Node not found")')
    dry_run_idx = source.find("if payload.dry_run:")
    destructive_idx = source.find("if not PendingAction.is_destructive(payload.action_type):")

    # Ensure all indices are found
    assert validate_idx > 0, "_validate_action_params not found"
    assert node_404_idx > 0, "404 check not found"
    assert dry_run_idx > 0, "dry_run branch not found"
    assert destructive_idx > 0, "destructive check not found"

    # dry_run comes after validate and 404
    assert dry_run_idx > validate_idx, "dry_run should be after _validate_action_params"
    assert dry_run_idx > node_404_idx, "dry_run should be after node 404 check"

    # dry_run comes before destructive check
    assert dry_run_idx < destructive_idx, "dry_run should be before destructive check"
