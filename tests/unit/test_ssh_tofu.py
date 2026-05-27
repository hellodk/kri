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
    result = await verify_or_store_host_key(node, "key-different", db)
    assert result is False
    db.add.assert_called_once()
    db.commit.assert_awaited_once()


def test_migration_023_exists():
    from pathlib import Path
    migration = Path("fleet_platform/db/migrations/versions/023_ssh_host_key.py")
    assert migration.exists()
    assert "ssh_host_key" in migration.read_text()


def test_node_model_has_ssh_host_key():
    from pathlib import Path
    src = Path("fleet_platform/models/node.py").read_text()
    assert "ssh_host_key" in src


def test_webssh_has_tofu_check():
    from pathlib import Path
    src = Path("fleet_platform/api/routes/webssh.py").read_text()
    assert "verify_or_store_host_key" in src


def test_ansible_tasks_no_unconditional_strict_host_key_no():
    from pathlib import Path
    src = Path("fleet_platform/workers/ansible_tasks.py").read_text()
    assert "StrictHostKeyChecking=no" not in src
