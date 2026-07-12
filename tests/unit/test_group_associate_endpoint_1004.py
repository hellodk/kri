# tests/unit/test_group_associate_endpoint_1004.py
"""Unit tests for #1004 — PUT /api/v1/groups/{group_id}/credential.

Associates an EXISTING Credential (picked from the credentials store) with a
group via ``set_group_credential`` (the ``credential_groups`` association),
distinct from PATCH /{group_id}/credentials which upserts a NEW Credential
from raw ssh_* fields. Validates both the group and the credential exist, and
shares the same 409-on-concurrent-write handling as C6.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.api.routes.groups import GroupCredentialAssociate, associate_group_credential


def _make_group(name="prod"):
    g = MagicMock()
    g.id = uuid.uuid4()
    g.name = name
    return g


def _claims():
    return {"sub": str(uuid.uuid4()), "email": "admin@example.com", "role": "admin"}


async def test_associate_group_credential_group_not_found_404():
    db = AsyncMock(spec=AsyncSession)
    group_result = MagicMock()
    group_result.scalar_one_or_none.return_value = None
    db.execute.side_effect = [group_result]

    payload = GroupCredentialAssociate(credential_id=uuid.uuid4())

    with pytest.raises(HTTPException) as exc_info:
        await associate_group_credential(
            group_id=uuid.uuid4(),
            payload=payload,
            db=db,
            claims=_claims(),
        )

    assert exc_info.value.status_code == 404
    assert "group" in exc_info.value.detail.lower()


async def test_associate_group_credential_credential_not_found_404():
    group = _make_group()
    db = AsyncMock(spec=AsyncSession)
    group_result = MagicMock()
    group_result.scalar_one_or_none.return_value = group
    db.execute.side_effect = [group_result]
    db.get = AsyncMock(return_value=None)  # credential lookup misses

    payload = GroupCredentialAssociate(credential_id=uuid.uuid4())

    with pytest.raises(HTTPException) as exc_info:
        await associate_group_credential(
            group_id=group.id,
            payload=payload,
            db=db,
            claims=_claims(),
        )

    assert exc_info.value.status_code == 404
    assert "credential" in exc_info.value.detail.lower()


async def test_associate_group_credential_success():
    group = _make_group()
    credential = MagicMock()
    credential.id = uuid.uuid4()
    credential.username = "deploy"

    db = AsyncMock(spec=AsyncSession)
    group_result = MagicMock()
    group_result.scalar_one_or_none.return_value = group
    db.execute.side_effect = [group_result]
    # 1st db.get: existence check; 2nd db.get: effective-credential lookup for the response.
    db.get = AsyncMock(side_effect=[credential, credential])

    payload = GroupCredentialAssociate(credential_id=credential.id)

    with (
        patch(
            "fleet_platform.api.routes.groups.set_group_credential",
            new=AsyncMock(),
        ) as mock_set,
        patch(
            "fleet_platform.api.routes.groups.get_group_credential_id",
            new=AsyncMock(return_value=credential.id),
        ),
        patch(
            "fleet_platform.api.routes.groups.owner_secret_flags",
            new=AsyncMock(return_value=(True, False)),
        ),
    ):
        result = await associate_group_credential(
            group_id=group.id,
            payload=payload,
            db=db,
            claims=_claims(),
        )

    mock_set.assert_awaited_once_with(db, group.id, credential.id)
    db.commit.assert_called_once()
    assert result["group_id"] == str(group.id)
    assert result["credential_id"] == str(credential.id)
    assert result["ssh_username"] == "deploy"
    assert result["has_ssh_password"] is True
    assert result["has_ssh_key"] is False


async def test_associate_group_credential_never_returns_a_secret():
    """The response dict must never carry a plaintext secret field."""
    group = _make_group()
    credential = MagicMock()
    credential.id = uuid.uuid4()
    credential.username = "deploy"

    db = AsyncMock(spec=AsyncSession)
    group_result = MagicMock()
    group_result.scalar_one_or_none.return_value = group
    db.execute.side_effect = [group_result]
    db.get = AsyncMock(side_effect=[credential, credential])

    payload = GroupCredentialAssociate(credential_id=credential.id)

    with (
        patch("fleet_platform.api.routes.groups.set_group_credential", new=AsyncMock()),
        patch(
            "fleet_platform.api.routes.groups.get_group_credential_id",
            new=AsyncMock(return_value=credential.id),
        ),
        patch(
            "fleet_platform.api.routes.groups.owner_secret_flags",
            new=AsyncMock(return_value=(False, True)),
        ),
    ):
        result = await associate_group_credential(
            group_id=group.id,
            payload=payload,
            db=db,
            claims=_claims(),
        )

    for key in result:
        assert "password" != key or isinstance(result[key], bool)
    assert "ssh_password" not in result
    assert "ssh_key" not in result
    assert result["ssh_auth_mode"] == "key"


async def test_associate_group_credential_commit_race_returns_409():
    """Same 409-on-race handling as PATCH /{group_id}/credentials (#1004 C6)."""
    group = _make_group()
    credential = MagicMock()
    credential.id = uuid.uuid4()

    db = AsyncMock(spec=AsyncSession)
    group_result = MagicMock()
    group_result.scalar_one_or_none.return_value = group
    db.execute.side_effect = [group_result]
    db.get = AsyncMock(return_value=credential)
    db.commit.side_effect = IntegrityError("insert into credential_groups", {}, Exception("duplicate key"))

    payload = GroupCredentialAssociate(credential_id=credential.id)

    with patch("fleet_platform.api.routes.groups.set_group_credential", new=AsyncMock()):
        with pytest.raises(HTTPException) as exc_info:
            await associate_group_credential(
                group_id=group.id,
                payload=payload,
                db=db,
                claims=_claims(),
            )

    assert exc_info.value.status_code == 409
    assert "concurrently" in exc_info.value.detail.lower()
    db.rollback.assert_called_once()
