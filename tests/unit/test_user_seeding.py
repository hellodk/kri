from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.models.user import User


def test_user_model_has_auth_provider_field():
    u = User(email="x@x.com", password_hash="h", role="admin", auth_provider="local")
    assert u.auth_provider == "local"


def test_user_model_auth_provider_defaults_local():
    u = User(email="x@x.com", password_hash="h", role="admin")
    # default is "local"
    assert u.auth_provider == "local"


@pytest.mark.asyncio
async def test_seed_creates_admin_when_absent():
    from fleet_platform.services.user_seeding import seed_local_users

    db = AsyncMock(spec=AsyncSession)
    exec_result = MagicMock()
    exec_result.scalar_one_or_none.return_value = None  # user absent
    db.execute.return_value = exec_result

    env = {
        "SEED_LOCAL_ADMIN_EMAIL": "admin@kri.local",
        "SEED_LOCAL_ADMIN_PASSWORD": "s3cret!",
    }
    with patch.dict("os.environ", env):
        await seed_local_users(db)

    db.add.assert_called_once()
    added: User = db.add.call_args[0][0]
    assert added.email == "admin@kri.local"
    assert added.role == "admin"
    assert added.auth_provider == "local"
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_seed_skips_when_user_exists():
    from fleet_platform.services.user_seeding import seed_local_users

    db = AsyncMock(spec=AsyncSession)
    exec_result = MagicMock()
    exec_result.scalar_one_or_none.return_value = User(
        email="admin@kri.local", password_hash="x", role="admin"
    )
    db.execute.return_value = exec_result

    env = {
        "SEED_LOCAL_ADMIN_EMAIL": "admin@kri.local",
        "SEED_LOCAL_ADMIN_PASSWORD": "s3cret!",
    }
    with patch.dict("os.environ", env):
        await seed_local_users(db)

    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_seed_noop_when_env_absent():
    from fleet_platform.services.user_seeding import seed_local_users

    db = AsyncMock(spec=AsyncSession)
    with patch.dict("os.environ", {}, clear=True):
        await seed_local_users(db)

    db.execute.assert_not_called()
    db.add.assert_not_called()
