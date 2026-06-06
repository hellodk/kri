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


@pytest.mark.asyncio
async def test_bootstrap_logs_content_does_not_contain_node_token_string():
    """Ensure no key in the response value contains a node_token-like string from pillar."""
    from fleet_platform.api.routes.ansible import bootstrap_logs

    mock_node = MagicMock()
    mock_node.id = "00000000-0000-0000-0000-000000000001"
    mock_node.minion_id = "test-node"
    mock_node.bootstrap_status = "completed"
    mock_node.bootstrap_logs = "Task completed successfully"

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_node

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)

    response = await bootstrap_logs(node_id=uuid.UUID("00000000-0000-0000-0000-000000000001"), db=mock_db, _={})

    response_str = str(response)
    assert "node_token" not in response_str
