"""Unit tests for SSH TOFU host key management (issue #86)."""

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_tofu_stores_key_on_first_connection():
    from fleet_platform.services.ssh_host_key_svc import verify_or_store_host_key

    node = MagicMock()
    node.ssh_host_key = None
    node.id = "node-1"
    node.hostname = "mm1"
    db = AsyncMock()
    result = await verify_or_store_host_key(node, "key-abc", db)
    assert result is True
    assert node.ssh_host_key == "key-abc"
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_tofu_matching_key_passes():
    from fleet_platform.services.ssh_host_key_svc import verify_or_store_host_key

    node = MagicMock()
    node.ssh_host_key = "key-abc"
    db = AsyncMock()
    result = await verify_or_store_host_key(node, "key-abc", db)
    assert result is True
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_tofu_mismatch_blocks_and_creates_event():
    from fleet_platform.services.ssh_host_key_svc import verify_or_store_host_key

    node = MagicMock()
    node.ssh_host_key = "key-original"
    node.id = "node-1"
    node.hostname = "mm1"
    db = AsyncMock()
    db.add = MagicMock()  # db.add is sync in AsyncSession
    result = await verify_or_store_host_key(node, "key-different", db)
    assert result is False
    db.add.assert_called_once()
    db.commit.assert_awaited_once()


def test_migration_023_exists():
    from pathlib import Path

    migration = Path("fleet_platform/db/migrations/versions/023_ssh_host_key.py")
    assert migration.exists()
    # Text check is appropriate here: migration DDL is a non-importable artifact;
    # the column name in the Alembic script is the only verifiable artifact at unit level.
    assert "ssh_host_key" in migration.read_text()


def test_node_model_has_ssh_host_key():
    from fleet_platform.models.node import Node

    assert hasattr(Node, "ssh_host_key"), "Node model must have an ssh_host_key column for TOFU host key storage (#86)"


def test_webssh_has_tofu_check():
    # verify_or_store_host_key is used inside a function body (local import). Use AST
    # to confirm the import appears in the webssh module, which is the only testable
    # signal without actually running the async WebSocket handler.
    import ast
    from pathlib import Path

    src = Path("fleet_platform/api/routes/webssh.py").read_text()
    tree = ast.parse(src)
    found = any(
        isinstance(node, ast.ImportFrom)
        and (node.module or "").endswith("ssh_host_key_svc")
        and any(alias.name == "verify_or_store_host_key" for alias in node.names)
        for node in ast.walk(tree)
    )
    assert found, "webssh must import verify_or_store_host_key from ssh_host_key_svc for TOFU verification (#86)"


def test_ansible_tasks_no_unconditional_strict_host_key_no():
    """AST-hardened absence guard: StrictHostKeyChecking=no must not appear as a string constant."""
    import ast
    from pathlib import Path

    src = Path("fleet_platform/workers/ansible_tasks.py").read_text()
    tree = ast.parse(src)
    str_consts = [
        node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]
    assert not any("StrictHostKeyChecking=no" in s for s in str_consts), (
        "ansible_tasks must not contain StrictHostKeyChecking=no — TOFU key pinning provides the security model (#86)"
    )
