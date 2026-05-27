# tests/unit/test_salt_tasks.py
"""Unit tests for salt_tasks — Salt HTTP API dispatch (issue #82 rewrite).

The docker exec approach has been removed. Salt commands now go via the Salt
HTTP API (salt-api). These tests verify the allowlist enforcement, API URL
not-configured error path, and the HTTP dispatch logic.
"""

from unittest.mock import MagicMock, patch

# ── Allowlist enforcement (unchanged from prior implementation) ───────────────

def test_run_salt_cmd_rejects_disallowed_function():
    """run_salt_cmd returns error dict for functions not in the allowlist."""
    from fleet_platform.workers.salt_tasks import run_salt_cmd

    result = run_salt_cmd.run(function="cmd.exec", target_minions=["minion1"])
    assert result["status"] == "error"
    assert "allowlist" in result["reason"].lower()


def test_run_salt_cmd_rejects_cmd_run():
    """cmd.run must be rejected — it allows arbitrary shell execution on fleet nodes."""
    from fleet_platform.workers.salt_tasks import _ALLOWED_SALT_FUNCTIONS, run_salt_cmd

    assert (
        "cmd.run" not in _ALLOWED_SALT_FUNCTIONS
    ), "cmd.run must never be in _ALLOWED_SALT_FUNCTIONS (arbitrary shell exec risk)"

    result = run_salt_cmd.run(function="cmd.run", target_minions=["minion1"], args=["id"])
    assert result["status"] == "error"
    assert "allowlist" in result["reason"].lower()


def test_allowlist_contains_expected_safe_functions():
    """The allowlist must contain the expected safe Salt functions."""
    from fleet_platform.workers.salt_tasks import _ALLOWED_SALT_FUNCTIONS

    required = {"test.ping", "state.apply", "grains.items", "pkg.list_pkgs"}
    assert required.issubset(_ALLOWED_SALT_FUNCTIONS), (
        f"Missing expected safe functions: {required - _ALLOWED_SALT_FUNCTIONS}"
    )


# ── SALT_API_URL not configured error ─────────────────────────────────────────

def test_run_salt_cmd_returns_error_when_api_not_configured():
    """Without SALT_API_URL set, run_salt_cmd returns a clear error."""
    from fleet_platform.workers import salt_tasks
    from fleet_platform.workers.salt_tasks import run_salt_cmd

    with patch.object(salt_tasks, "_SALT_API_URL", ""):
        result = run_salt_cmd.run(function="test.ping", target_minions=["minion1"])

    assert result["status"] == "error"
    assert "SALT_API_URL" in result["reason"]


def test_apply_salt_state_returns_error_when_api_not_configured():
    """Without SALT_API_URL set, apply_salt_state returns a clear error."""
    from fleet_platform.workers import salt_tasks
    from fleet_platform.workers.salt_tasks import apply_salt_state

    with patch.object(salt_tasks, "_SALT_API_URL", ""):
        result = apply_salt_state.run(
            state_name="kri.init",
            target_minions=["minion1"],
        )

    assert result["status"] == "error"
    assert "SALT_API_URL" in result["reason"]


# ── HTTP API dispatch ─────────────────────────────────────────────────────────

def test_run_salt_cmd_dispatches_via_http_api():
    """An allowlisted function triggers a POST to the salt-api /run endpoint."""

    from fleet_platform.workers import salt_tasks
    from fleet_platform.workers.salt_tasks import run_salt_cmd

    fake_response = MagicMock()
    fake_response.raise_for_status = MagicMock()
    fake_response.json.return_value = {"return": [{"minion1": True}]}

    with (
        patch.object(salt_tasks, "_SALT_API_URL", "http://salt-master:8080"),
        patch.object(salt_tasks, "_SALT_API_USER", "saltuser"),
        patch.object(salt_tasks, "_SALT_API_PASSWORD", "secret"),
        patch("fleet_platform.workers.salt_tasks.requests.post", return_value=fake_response) as mock_post,
    ):
        result = run_salt_cmd.run(function="test.ping", target_minions=["minion1"])

    assert result["status"] == "ok"
    assert result["result"] == [{"minion1": True}]
    mock_post.assert_called_once()
    call_kwargs = mock_post.call_args
    # URL must point to /run endpoint
    assert call_kwargs[0][0] == "http://salt-master:8080/run"
    payload = call_kwargs[1]["json"]
    assert payload["fun"] == "test.ping"
    assert payload["tgt"] == "minion1"


def test_apply_salt_state_dispatches_via_http_api():
    """apply_salt_state sends state name and optional pillar to salt-api."""
    from fleet_platform.workers import salt_tasks
    from fleet_platform.workers.salt_tasks import apply_salt_state

    fake_response = MagicMock()
    fake_response.raise_for_status = MagicMock()
    fake_response.json.return_value = {"return": [{"minion1": {"state.apply": True}}]}

    with (
        patch.object(salt_tasks, "_SALT_API_URL", "http://salt-master:8080"),
        patch.object(salt_tasks, "_SALT_API_USER", "saltuser"),
        patch.object(salt_tasks, "_SALT_API_PASSWORD", "secret"),
        patch("fleet_platform.workers.salt_tasks.requests.post", return_value=fake_response) as mock_post,
    ):
        result = apply_salt_state.run(
            state_name="kri.init",
            target_minions=["minion1", "minion2"],
            pillar_data={"key": "value"},
        )

    assert result["status"] == "ok"
    payload = mock_post.call_args[1]["json"]
    assert payload["fun"] == "state.apply"
    assert payload["arg"] == ["kri.init"]
    assert payload["kwarg"] == {"pillar": {"key": "value"}}
    # Target should be comma-joined list
    assert payload["tgt"] == "minion1,minion2"


def test_run_salt_api_handles_connection_error():
    """A ConnectionError to salt-api returns a descriptive error dict."""
    import requests

    from fleet_platform.workers import salt_tasks
    from fleet_platform.workers.salt_tasks import run_salt_cmd

    with (
        patch.object(salt_tasks, "_SALT_API_URL", "http://salt-master:8080"),
        patch.object(salt_tasks, "_SALT_API_USER", "u"),
        patch.object(salt_tasks, "_SALT_API_PASSWORD", "p"),
        patch(
            "fleet_platform.workers.salt_tasks.requests.post",
            side_effect=requests.ConnectionError("Connection refused"),
        ),
    ):
        result = run_salt_cmd.run(function="test.ping", target_minions=["minion1"])

    assert result["status"] == "error"
    assert "salt-master:8080" in result["reason"] or "Cannot reach" in result["reason"]


# ── No docker exec remnants ───────────────────────────────────────────────────

def test_salt_tasks_does_not_import_subprocess():
    """salt_tasks.py must not import subprocess — docker exec is removed (issue #82)."""
    import ast
    from pathlib import Path

    src = (
        Path(__file__).parent.parent.parent
        / "fleet_platform" / "workers" / "salt_tasks.py"
    ).read_text()
    tree = ast.parse(src)
    imports = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
    ]
    imported_names = []
    for node in imports:
        if isinstance(node, ast.Import):
            imported_names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported_names.append(node.module or "")
    assert "subprocess" not in imported_names, (
        "salt_tasks.py must not import subprocess — docker exec was removed in issue #82. "
        "Use Salt HTTP API instead."
    )
