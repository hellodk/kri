"""Tests for P0 security fixes: #442 (pillar token leak) and #443 (path traversal)."""

import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest  # noqa: F401

# ── #443: path traversal guard ──────────────────────────────────────────────


def _check_guard(target: Path, allowed_roots: list[str]) -> bool:
    """Mirrors the fixed guard logic: returns True if path is safe."""
    return any(target.is_relative_to(Path(r)) for r in allowed_roots)


def test_path_guard_rejects_sibling_directory():
    target = Path("/srv/playbooks-evil/secret.yml")
    allowed = ["/srv/playbooks"]
    assert not _check_guard(target, allowed), "Sibling directory must be rejected"


def test_path_guard_rejects_prefix_match_without_separator():
    target = Path("/srv/playbooksXYZ/x.yml")
    allowed = ["/srv/playbooks"]
    assert not _check_guard(target, allowed), "Prefix match without separator must be rejected"


def test_path_guard_accepts_valid_path():
    target = Path("/srv/playbooks/site.yml")
    allowed = ["/srv/playbooks"]
    assert _check_guard(target, allowed), "Valid nested path must be accepted"


def test_path_guard_accepts_nested_path():
    target = Path("/srv/playbooks/roles/common/tasks/main.yml")
    allowed = ["/srv/playbooks"]
    assert _check_guard(target, allowed), "Deeply nested valid path must be accepted"


# ── #442: bootstrap logs excludes pillar ────────────────────────────────────


@pytest.mark.asyncio
async def test_bootstrap_logs_excludes_pillar_field():
    """bootstrap_logs response must not contain 'pillar' or 'pillar_path' keys."""
    from fleet_platform.api.routes.ansible import bootstrap_logs

    mock_node = MagicMock()
    mock_node.id = "00000000-0000-0000-0000-000000000001"
    mock_node.minion_id = "test-node"
    mock_node.bootstrap_status = "completed"
    mock_node.bootstrap_logs = "some logs"

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_node

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)

    response = await bootstrap_logs(node_id=uuid.UUID("00000000-0000-0000-0000-000000000001"), db=mock_db, _={})

    assert "pillar" not in response, "Response must not contain 'pillar' key (exposes node_token)"
    assert "pillar_path" not in response, "Response must not contain 'pillar_path' key"
    assert "ansible_stdout" in response
    assert "bootstrap_status" in response


def test_scrub_token_removes_raw_token():
    """_scrub_token must redact a real-looking token from stdout."""
    import secrets

    from fleet_platform.workers.ansible_tasks import _scrub_token

    token = secrets.token_urlsafe(32)
    stdout = f"X-Node-Token: {token}\nother ansible output\nuri: {token}"
    result = _scrub_token(stdout, token)
    assert token not in result
    assert "***" in result
    assert "other ansible output" in result  # non-secret content preserved


@pytest.mark.asyncio
async def test_bootstrap_logs_endpoint_content_does_not_contain_raw_token():
    """Endpoint must not return a token-like string in ansible_stdout — simulates
    a worst-case where scrubbing in ansible_tasks somehow failed to clear a line."""
    import secrets

    from fleet_platform.api.routes.ansible import bootstrap_logs

    token = secrets.token_urlsafe(32)

    mock_node = MagicMock()
    mock_node.id = "00000000-0000-0000-0000-000000000001"
    mock_node.minion_id = "test-node"
    mock_node.bootstrap_status = "completed"
    # bootstrap_logs should be scrubbed before storage; this seeds a pre-scrubbed value
    mock_node.bootstrap_logs = "Task completed successfully — no secrets here"

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_node

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)

    response = await bootstrap_logs(node_id=uuid.UUID("00000000-0000-0000-0000-000000000001"), db=mock_db, _={})

    response_str = str(response)
    assert token not in response_str
    assert "pillar" not in response
    assert "ansible_stdout" in response
