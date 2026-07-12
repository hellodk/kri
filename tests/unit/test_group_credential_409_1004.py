# tests/unit/test_group_credential_409_1004.py
"""Unit tests for #1004 C6 — PATCH /groups/{group_id}/credentials must return
409 (not an unhandled 500) when a concurrent PATCH races on the
``credential_groups`` UNIQUE(group_id) insert (delete-then-insert upsert in
``set_group_credential``).
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.api.routes.groups import GroupCredentialsUpdate, update_group_credentials


def _make_group(name="prod"):
    g = MagicMock()
    g.id = uuid.uuid4()
    g.name = name
    g.session_max_mins = 60
    g.session_retention_days = 7
    return g


def _claims():
    return {"sub": str(uuid.uuid4()), "email": "admin@example.com", "role": "admin"}


async def test_update_group_credentials_commit_race_returns_409():
    """Two concurrent PATCHes racing on the credential_groups UNIQUE(group_id)
    insert must surface as HTTP 409, not propagate the raw IntegrityError
    (which FastAPI would otherwise turn into a 500)."""
    group = _make_group()

    db = AsyncMock(spec=AsyncSession)
    group_result = MagicMock()
    group_result.scalar_one_or_none.return_value = group
    db.execute.side_effect = [group_result]
    db.commit.side_effect = IntegrityError("insert into credential_groups", {}, Exception("duplicate key"))

    payload = GroupCredentialsUpdate(ssh_username="deploy", ssh_password="pw")

    with (
        patch(
            "fleet_platform.api.routes.groups.get_group_credential_id",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "fleet_platform.api.routes.groups.upsert_owner_ssh_credential",
            new=AsyncMock(return_value=uuid.uuid4()),
        ),
        patch(
            "fleet_platform.api.routes.groups.set_group_credential",
            new=AsyncMock(),
        ),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await update_group_credentials(
                group_id=group.id,
                payload=payload,
                db=db,
                claims=_claims(),
            )

    assert exc_info.value.status_code == 409
    assert "concurrently" in exc_info.value.detail.lower()
    db.rollback.assert_called_once()


async def test_update_group_credentials_rolls_back_before_raising():
    """The rollback must happen BEFORE the 409 is raised (session must not be
    left in a failed-transaction state for the caller)."""
    group = _make_group()

    db = AsyncMock(spec=AsyncSession)
    group_result = MagicMock()
    group_result.scalar_one_or_none.return_value = group
    db.execute.side_effect = [group_result]
    db.commit.side_effect = IntegrityError("insert into credential_groups", {}, Exception("duplicate key"))

    call_order = []
    db.rollback.side_effect = lambda: call_order.append("rollback")

    payload = GroupCredentialsUpdate(ssh_key="PRIVATE_KEY", ssh_auth_mode="key")

    with (
        patch(
            "fleet_platform.api.routes.groups.get_group_credential_id",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "fleet_platform.api.routes.groups.upsert_owner_ssh_credential",
            new=AsyncMock(return_value=uuid.uuid4()),
        ),
        patch(
            "fleet_platform.api.routes.groups.set_group_credential",
            new=AsyncMock(),
        ),
    ):
        with pytest.raises(HTTPException):
            await update_group_credentials(
                group_id=group.id,
                payload=payload,
                db=db,
                claims=_claims(),
            )

    assert call_order == ["rollback"]


async def test_update_group_credentials_success_when_no_race():
    """Sanity check: a non-racing commit still returns the effective mapping
    (this must keep working after the try/except wrap)."""
    group = _make_group()
    effective_id = uuid.uuid4()
    cred = MagicMock()
    cred.username = "deploy"

    db = AsyncMock(spec=AsyncSession)
    group_result = MagicMock()
    group_result.scalar_one_or_none.return_value = group
    db.execute.side_effect = [group_result]
    db.get = AsyncMock(return_value=cred)

    payload = GroupCredentialsUpdate(ssh_username="deploy", ssh_password="pw")

    with (
        patch(
            "fleet_platform.api.routes.groups.get_group_credential_id",
            new=AsyncMock(side_effect=[None, effective_id]),
        ),
        patch(
            "fleet_platform.api.routes.groups.upsert_owner_ssh_credential",
            new=AsyncMock(return_value=effective_id),
        ),
        patch(
            "fleet_platform.api.routes.groups.set_group_credential",
            new=AsyncMock(),
        ),
        patch(
            "fleet_platform.api.routes.groups.owner_secret_flags",
            new=AsyncMock(return_value=(True, False)),
        ),
    ):
        result = await update_group_credentials(
            group_id=group.id,
            payload=payload,
            db=db,
            claims=_claims(),
        )

    assert result["ssh_username"] == "deploy"
    assert result["has_ssh_password"] is True
    assert result["has_ssh_key"] is False
    db.commit.assert_called_once()
    db.rollback.assert_not_called()
