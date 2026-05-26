# tests/unit/test_node_secrets_svc.py
"""Unit tests for fleet_platform.services.node_secrets_svc."""
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import yaml
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.services.node_secrets_svc import (
    _DEFAULT_PILLAR_DIR,
    _get_pillar_dir,
    delete_secret,
    get_decrypted_secrets,
    get_secrets,
    upsert_secret,
    write_node_pillar,
)
from fleet_platform.services.platform_settings_svc import encrypt_secret

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_db_single(scalar_one_or_none_val=None, scalars_all_val=None):
    """Build an AsyncMock db for a single execute() call."""
    db = AsyncMock(spec=AsyncSession)
    result = MagicMock()
    result.scalar_one_or_none.return_value = scalar_one_or_none_val
    if scalars_all_val is not None:
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = scalars_all_val
        result.scalars.return_value = scalars_mock
    db.execute.return_value = result
    return db


def _make_db_side_effect(*results):
    """Build an AsyncMock db whose execute() calls return results in order."""
    db = AsyncMock(spec=AsyncSession)
    side_effects = []
    for r in results:
        side_effects.append(r)
    db.execute.side_effect = side_effects
    return db


def _exec_result(scalar_one_or_none=None, scalars_all=None):
    result = MagicMock()
    result.scalar_one_or_none.return_value = scalar_one_or_none
    if scalars_all is not None:
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = scalars_all
        result.scalars.return_value = scalars_mock
    return result


def _platform_row(value):
    row = MagicMock()
    row.value = value
    return row


def _node_secret(key, encrypted_value):
    s = MagicMock()
    s.key = key
    s.encrypted_value = encrypted_value
    return s


# ---------------------------------------------------------------------------
# Test 1: _get_pillar_dir returns path from DB setting
# ---------------------------------------------------------------------------

async def test_get_pillar_dir_from_setting():
    row = _platform_row("/custom/pillar")
    db = _make_db_single(scalar_one_or_none_val=row)

    result = await _get_pillar_dir(db)

    assert result == Path("/custom/pillar")


# ---------------------------------------------------------------------------
# Test 2: _get_pillar_dir falls back to default when DB returns None
# ---------------------------------------------------------------------------

async def test_get_pillar_dir_default():
    db = _make_db_single(scalar_one_or_none_val=None)

    result = await _get_pillar_dir(db)

    assert result == _DEFAULT_PILLAR_DIR


# ---------------------------------------------------------------------------
# Test 3: get_secrets returns list of NodeSecret rows
# ---------------------------------------------------------------------------

async def test_get_secrets_returns_list():
    secret1 = _node_secret("db_pass", "enc1")
    secret2 = _node_secret("api_key", "enc2")
    db = _make_db_single(scalars_all_val=[secret1, secret2])

    result = await get_secrets(db, uuid.uuid4())

    assert len(result) == 2
    assert result[0].key == "db_pass"
    assert result[1].key == "api_key"


# ---------------------------------------------------------------------------
# Test 4: upsert_secret creates a new NodeSecret when none exists
# ---------------------------------------------------------------------------

async def test_upsert_secret_creates_new():
    db = AsyncMock(spec=AsyncSession)

    # First execute: select for existing → None
    result1 = _exec_result(scalar_one_or_none=None)
    db.execute.return_value = result1

    with patch("fleet_platform.services.node_secrets_svc.encrypt_secret", return_value="encrypted"):
        await upsert_secret(db, uuid.uuid4(), "my_key", "plaintext")

    db.add.assert_called_once()
    db.commit.assert_called_once()
    db.refresh.assert_called_once()


# ---------------------------------------------------------------------------
# Test 5: upsert_secret updates encrypted_value on existing secret
# ---------------------------------------------------------------------------

async def test_upsert_secret_updates_existing():
    existing = MagicMock()
    existing.encrypted_value = "old_enc"
    existing.description = "original desc"

    db = AsyncMock(spec=AsyncSession)
    result1 = _exec_result(scalar_one_or_none=existing)
    db.execute.return_value = result1

    with patch("fleet_platform.services.node_secrets_svc.encrypt_secret", return_value="new_enc"):
        await upsert_secret(db, uuid.uuid4(), "my_key", "newvalue")

    assert existing.encrypted_value == "new_enc"
    # description not passed → must not be changed
    assert existing.description == "original desc"
    db.add.assert_not_called()
    db.commit.assert_called_once()


# ---------------------------------------------------------------------------
# Test 6: upsert_secret updates description when provided
# ---------------------------------------------------------------------------

async def test_upsert_secret_updates_description_when_provided():
    existing = MagicMock()
    existing.encrypted_value = "old_enc"
    existing.description = "old desc"

    db = AsyncMock(spec=AsyncSession)
    result1 = _exec_result(scalar_one_or_none=existing)
    db.execute.return_value = result1

    with patch("fleet_platform.services.node_secrets_svc.encrypt_secret", return_value="new_enc"):
        await upsert_secret(db, uuid.uuid4(), "my_key", "newvalue", description="new desc")

    assert existing.description == "new desc"


# ---------------------------------------------------------------------------
# Test 7: delete_secret returns False when secret not found
# ---------------------------------------------------------------------------

async def test_delete_secret_not_found():
    db = _make_db_single(scalar_one_or_none_val=None)

    result = await delete_secret(db, uuid.uuid4(), "missing_key")

    assert result is False
    db.delete.assert_not_called()
    db.commit.assert_not_called()


# ---------------------------------------------------------------------------
# Test 8: delete_secret returns True and calls db.delete when found
# ---------------------------------------------------------------------------

async def test_delete_secret_found():
    secret = MagicMock()
    db = _make_db_single(scalar_one_or_none_val=secret)

    result = await delete_secret(db, uuid.uuid4(), "existing_key")

    assert result is True
    db.delete.assert_called_once_with(secret)
    db.commit.assert_called_once()


# ---------------------------------------------------------------------------
# Test 9: get_decrypted_secrets roundtrip with real encrypt/decrypt
# ---------------------------------------------------------------------------

async def test_get_decrypted_secrets_roundtrip():
    node_id = uuid.uuid4()
    encrypted = encrypt_secret("supersecret")
    secret = _node_secret("db_pass", encrypted)

    db = _make_db_single(scalars_all_val=[secret])

    result = await get_decrypted_secrets(db, node_id)

    assert result == {"db_pass": "supersecret"}


# ---------------------------------------------------------------------------
# Test 10: get_decrypted_secrets skips entries with garbage encrypted_value
# ---------------------------------------------------------------------------

async def test_get_decrypted_secrets_skips_bad_value():
    node_id = uuid.uuid4()
    good_enc = encrypt_secret("goodvalue")
    good = _node_secret("good_key", good_enc)
    bad = _node_secret("bad_key", "not-valid-fernet!!!")

    db = _make_db_single(scalars_all_val=[good, bad])

    result = await get_decrypted_secrets(db, node_id)

    assert "good_key" in result
    assert result["good_key"] == "goodvalue"
    assert "bad_key" not in result


# ---------------------------------------------------------------------------
# Test 11: write_node_pillar creates file with correct YAML
# ---------------------------------------------------------------------------

async def test_write_node_pillar_creates_file(tmp_path):
    node_id = uuid.uuid4()
    minion_id = "mac-mini-01"

    db = AsyncMock(spec=AsyncSession)

    with (
        patch("fleet_platform.services.node_secrets_svc._get_pillar_dir", return_value=tmp_path),
        patch(
            "fleet_platform.services.node_secrets_svc.get_decrypted_secrets",
            return_value={"db_pass": "secret", "api_key": "abc123"},
        ),
    ):
        await write_node_pillar(node_id, minion_id, db)

    sls_path = tmp_path / f"{minion_id}.sls"
    assert sls_path.exists()
    content = sls_path.read_text()
    parsed = yaml.safe_load(content.split("\n", 1)[1])  # skip the comment line
    assert parsed["db_pass"] == "secret"
    assert parsed["api_key"] == "abc123"


# ---------------------------------------------------------------------------
# Test 12: write_node_pillar merges with existing pillar content
# ---------------------------------------------------------------------------

async def test_write_node_pillar_merges_existing(tmp_path):
    node_id = uuid.uuid4()
    minion_id = "mac-mini-02"

    # Pre-write existing pillar content
    sls_path = tmp_path / f"{minion_id}.sls"
    sls_path.write_text(yaml.dump({"fleet_platform": {"node_token": "tok123"}}))

    db = AsyncMock(spec=AsyncSession)

    with (
        patch("fleet_platform.services.node_secrets_svc._get_pillar_dir", return_value=tmp_path),
        patch(
            "fleet_platform.services.node_secrets_svc.get_decrypted_secrets",
            return_value={"db_pass": "secret"},
        ),
    ):
        await write_node_pillar(node_id, minion_id, db)

    parsed = yaml.safe_load(sls_path.read_text().split("\n", 1)[1])
    # Existing key preserved
    assert parsed["fleet_platform"]["node_token"] == "tok123"
    # New secret merged in
    assert parsed["db_pass"] == "secret"


# ---------------------------------------------------------------------------
# Test 13: get_secrets returns empty list when db returns none
# ---------------------------------------------------------------------------

async def test_get_secrets_returns_empty_list():
    db = _make_db_single(scalars_all_val=[])

    result = await get_secrets(db, uuid.uuid4())

    assert result == []


# ---------------------------------------------------------------------------
# Test 14: get_decrypted_secrets returns empty dict when no secrets
# ---------------------------------------------------------------------------

async def test_get_decrypted_secrets_empty():
    db = _make_db_single(scalars_all_val=[])

    result = await get_decrypted_secrets(db, uuid.uuid4())

    assert result == {}
