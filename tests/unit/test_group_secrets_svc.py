# tests/unit/test_group_secrets_svc.py
"""Unit tests for fleet_platform.services.group_secrets_svc."""
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import yaml
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.services.platform_settings_svc import decrypt_secret, encrypt_secret
from fleet_platform.services.group_secrets_svc import (
    _DEFAULT_PILLAR_DIR,
    _get_pillar_dir,
    get_secrets,
    upsert_secret,
    delete_secret,
    get_decrypted_secrets,
    write_group_pillar,
    rebuild_top_sls,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _exec_result(scalar_one_or_none=None, scalars_all=None):
    result = MagicMock()
    result.scalar_one_or_none.return_value = scalar_one_or_none
    if scalars_all is not None:
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = scalars_all
        result.scalars.return_value = scalars_mock
    return result


def _make_db_single(scalar_one_or_none_val=None, scalars_all_val=None):
    db = AsyncMock(spec=AsyncSession)
    result = _exec_result(
        scalar_one_or_none=scalar_one_or_none_val,
        scalars_all=scalars_all_val,
    )
    db.execute.return_value = result
    return db


def _group_secret(key, encrypted_value):
    s = MagicMock()
    s.key = key
    s.encrypted_value = encrypted_value
    return s


def _platform_row(value):
    row = MagicMock()
    row.value = value
    return row


def _node(minion_id, node_id=None):
    n = MagicMock()
    n.id = node_id or uuid.uuid4()
    n.minion_id = minion_id
    return n


def _group(name, group_id=None):
    g = MagicMock()
    g.id = group_id or uuid.uuid4()
    g.name = name
    return g


def _member(node_id):
    m = MagicMock()
    m.node_id = node_id
    return m


# ---------------------------------------------------------------------------
# Test 1: get_secrets returns list in order
# ---------------------------------------------------------------------------

async def test_get_secrets_ordered():
    s1 = _group_secret("alpha", "enc1")
    s2 = _group_secret("zeta", "enc2")
    db = _make_db_single(scalars_all_val=[s1, s2])

    result = await get_secrets(db, uuid.uuid4())

    assert len(result) == 2
    assert result[0].key == "alpha"
    assert result[1].key == "zeta"


# ---------------------------------------------------------------------------
# Test 2: upsert creates new GroupSecret when none found
# ---------------------------------------------------------------------------

async def test_upsert_creates_new_secret():
    db = AsyncMock(spec=AsyncSession)
    db.execute.return_value = _exec_result(scalar_one_or_none=None)

    with patch("fleet_platform.services.group_secrets_svc.encrypt_secret", return_value="enc"):
        await upsert_secret(db, uuid.uuid4(), "mykey", "myvalue")

    db.add.assert_called_once()
    db.commit.assert_called_once()
    db.refresh.assert_called_once()


# ---------------------------------------------------------------------------
# Test 3: upsert updates encrypted_value and leaves description alone when None
# ---------------------------------------------------------------------------

async def test_upsert_updates_existing():
    existing = MagicMock()
    existing.encrypted_value = "old"
    existing.description = "keep me"

    db = AsyncMock(spec=AsyncSession)
    db.execute.return_value = _exec_result(scalar_one_or_none=existing)

    with patch("fleet_platform.services.group_secrets_svc.encrypt_secret", return_value="new_enc"):
        await upsert_secret(db, uuid.uuid4(), "mykey", "newval")

    assert existing.encrypted_value == "new_enc"
    assert existing.description == "keep me"
    db.add.assert_not_called()


# ---------------------------------------------------------------------------
# Test 4: upsert updates description when provided
# ---------------------------------------------------------------------------

async def test_upsert_updates_description_when_provided():
    existing = MagicMock()
    existing.encrypted_value = "old"
    existing.description = "old desc"

    db = AsyncMock(spec=AsyncSession)
    db.execute.return_value = _exec_result(scalar_one_or_none=existing)

    with patch("fleet_platform.services.group_secrets_svc.encrypt_secret", return_value="new_enc"):
        await upsert_secret(db, uuid.uuid4(), "mykey", "newval", description="new desc")

    assert existing.description == "new desc"


# ---------------------------------------------------------------------------
# Test 5: delete_secret returns False when not found
# ---------------------------------------------------------------------------

async def test_delete_not_found():
    db = _make_db_single(scalar_one_or_none_val=None)

    result = await delete_secret(db, uuid.uuid4(), "missing")

    assert result is False
    db.delete.assert_not_called()
    db.commit.assert_not_called()


# ---------------------------------------------------------------------------
# Test 6: delete_secret returns True and calls db.delete
# ---------------------------------------------------------------------------

async def test_delete_found():
    secret = MagicMock()
    db = _make_db_single(scalar_one_or_none_val=secret)

    result = await delete_secret(db, uuid.uuid4(), "existing")

    assert result is True
    db.delete.assert_called_once_with(secret)
    db.commit.assert_called_once()


# ---------------------------------------------------------------------------
# Test 7: get_decrypted_secrets real encrypt/decrypt roundtrip
# ---------------------------------------------------------------------------

async def test_get_decrypted_secrets_success():
    group_id = uuid.uuid4()
    encrypted = encrypt_secret("groupsecret")
    secret = _group_secret("db_pass", encrypted)
    db = _make_db_single(scalars_all_val=[secret])

    result = await get_decrypted_secrets(db, group_id)

    assert result == {"db_pass": "groupsecret"}


# ---------------------------------------------------------------------------
# Test 8: get_decrypted_secrets skips bad encrypted_value silently
# ---------------------------------------------------------------------------

async def test_get_decrypted_secrets_bad_value_skipped():
    group_id = uuid.uuid4()
    good_enc = encrypt_secret("ok")
    good = _group_secret("good", good_enc)
    bad = _group_secret("bad", "!!!not-fernet!!!")
    db = _make_db_single(scalars_all_val=[good, bad])

    result = await get_decrypted_secrets(db, group_id)

    assert "good" in result
    assert result["good"] == "ok"
    assert "bad" not in result


# ---------------------------------------------------------------------------
# Test 9: write_group_pillar creates sls file with correct content
# ---------------------------------------------------------------------------

async def test_write_group_pillar_creates_file(tmp_path):
    group_id = uuid.uuid4()
    db = AsyncMock(spec=AsyncSession)

    with (
        patch("fleet_platform.services.group_secrets_svc._get_pillar_dir", return_value=tmp_path),
        patch(
            "fleet_platform.services.group_secrets_svc.get_decrypted_secrets",
            return_value={"token": "abc", "host": "db.local"},
        ),
    ):
        await write_group_pillar(group_id, db)

    sls_path = tmp_path / f"group_{group_id}.sls"
    assert sls_path.exists()
    content = sls_path.read_text()
    assert "# Auto-generated by kri" in content
    parsed = yaml.safe_load(content.split("\n", 1)[1])
    assert parsed["token"] == "abc"
    assert parsed["host"] == "db.local"


# ---------------------------------------------------------------------------
# Test 10: rebuild_top_sls with no nodes and no groups → minimal top.sls
# ---------------------------------------------------------------------------

async def test_rebuild_top_sls_empty(tmp_path):
    db = AsyncMock(spec=AsyncSession)

    # execute calls in order:
    #   1. _get_pillar_dir → pillar_dir row (None → default, but we patch the function)
    #   2. select(Node)    → nodes (empty)
    #   3. select(Group)   → groups (empty)
    nodes_result = _exec_result(scalars_all=[])
    groups_result = _exec_result(scalars_all=[])
    db.execute.side_effect = [nodes_result, groups_result]

    with patch("fleet_platform.services.group_secrets_svc._get_pillar_dir", return_value=tmp_path):
        with patch("builtins.open", wraps=open):
            with patch("fcntl.flock"):
                await rebuild_top_sls(db)

    top_path = tmp_path / "top.sls"
    assert top_path.exists()
    content = top_path.read_text()
    assert "# Auto-generated by kri" in content
    assert "base:" in content
    # No minion entries expected
    assert "mac-" not in content


# ---------------------------------------------------------------------------
# Test 11: rebuild_top_sls with one node and one non-global group with secrets
# ---------------------------------------------------------------------------

async def test_rebuild_top_sls_with_node_and_group(tmp_path):
    db = AsyncMock(spec=AsyncSession)

    node_id = uuid.uuid4()
    group_id = uuid.uuid4()

    node = _node("mac-01", node_id=node_id)
    group = _group("devops", group_id=group_id)
    secret = MagicMock()  # any truthy object = group has secrets
    member = _member(node_id)

    # execute() calls in rebuild_top_sls order (no _get_pillar_dir call — it's patched):
    #   1. select(Node)               → [node]
    #   2. select(Group)              → [group]
    #   3. select(GroupSecret) limit1 → secret  (group has secrets)
    #   4. select(GroupMember)        → [member]
    nodes_result = _exec_result(scalars_all=[node])
    groups_result = _exec_result(scalars_all=[group])
    has_secrets_result = _exec_result(scalar_one_or_none=secret)
    members_result = _exec_result(scalars_all=[member])
    db.execute.side_effect = [nodes_result, groups_result, has_secrets_result, members_result]

    with patch("fleet_platform.services.group_secrets_svc._get_pillar_dir", return_value=tmp_path):
        with patch("fcntl.flock"):
            await rebuild_top_sls(db)

    top_path = tmp_path / "top.sls"
    assert top_path.exists()
    content = top_path.read_text()

    # minion entry present
    assert "'mac-01':" in content
    # its own SLS listed
    assert "- mac-01" in content
    # group pillar referenced
    assert f"- group_{group_id}" in content


# ---------------------------------------------------------------------------
# Test 12: rebuild_top_sls — global group ("all") goes to '*' entry
# ---------------------------------------------------------------------------

async def test_rebuild_top_sls_global_group_goes_to_star(tmp_path):
    db = AsyncMock(spec=AsyncSession)

    group_id = uuid.uuid4()
    group = _group("all", group_id=group_id)
    secret = MagicMock()

    nodes_result = _exec_result(scalars_all=[])
    groups_result = _exec_result(scalars_all=[group])
    has_secrets_result = _exec_result(scalar_one_or_none=secret)
    db.execute.side_effect = [nodes_result, groups_result, has_secrets_result]

    with patch("fleet_platform.services.group_secrets_svc._get_pillar_dir", return_value=tmp_path):
        with patch("fcntl.flock"):
            await rebuild_top_sls(db)

    content = (tmp_path / "top.sls").read_text()
    assert "  '*':" in content
    assert "    - common" in content


# ---------------------------------------------------------------------------
# Test 13: rebuild_top_sls — group with no secrets is skipped
# ---------------------------------------------------------------------------

async def test_rebuild_top_sls_group_without_secrets_skipped(tmp_path):
    db = AsyncMock(spec=AsyncSession)

    node_id = uuid.uuid4()
    group_id = uuid.uuid4()
    node = _node("mac-02", node_id=node_id)
    group = _group("empty-group", group_id=group_id)

    nodes_result = _exec_result(scalars_all=[node])
    groups_result = _exec_result(scalars_all=[group])
    has_secrets_result = _exec_result(scalar_one_or_none=None)  # no secrets
    db.execute.side_effect = [nodes_result, groups_result, has_secrets_result]

    with patch("fleet_platform.services.group_secrets_svc._get_pillar_dir", return_value=tmp_path):
        with patch("fcntl.flock"):
            await rebuild_top_sls(db)

    content = (tmp_path / "top.sls").read_text()
    # group pillar must NOT appear
    assert f"group_{group_id}" not in content
    # node's own pillar still appears
    assert "mac-02" in content


# ---------------------------------------------------------------------------
# Test 14: get_secrets returns empty list when db has nothing
# ---------------------------------------------------------------------------

async def test_get_secrets_empty_list():
    db = _make_db_single(scalars_all_val=[])

    result = await get_secrets(db, uuid.uuid4())

    assert result == []


# ---------------------------------------------------------------------------
# Test 15: get_decrypted_secrets returns empty dict when no secrets
# ---------------------------------------------------------------------------

async def test_get_decrypted_secrets_empty():
    db = _make_db_single(scalars_all_val=[])

    result = await get_decrypted_secrets(db, uuid.uuid4())

    assert result == {}


# ---------------------------------------------------------------------------
# Test 16: _get_pillar_dir returns setting value when found
# ---------------------------------------------------------------------------

async def test_get_pillar_dir_from_setting_group():
    from sqlalchemy.ext.asyncio import AsyncSession
    db = AsyncMock(spec=AsyncSession)
    row = MagicMock()
    row.value = "/opt/pillar"
    result = MagicMock()
    result.scalar_one_or_none.return_value = row
    db.execute.return_value = result
    path = await _get_pillar_dir(db)
    assert path == Path("/opt/pillar")


# ---------------------------------------------------------------------------
# Test 17: _get_pillar_dir returns default when setting not found
# ---------------------------------------------------------------------------

async def test_get_pillar_dir_default_group():
    from sqlalchemy.ext.asyncio import AsyncSession
    db = AsyncMock(spec=AsyncSession)
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    db.execute.return_value = result
    path = await _get_pillar_dir(db)
    assert path == _DEFAULT_PILLAR_DIR
