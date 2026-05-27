# tests/integration/test_platform_settings_svc.py
"""Integration tests for fleet_platform.services.platform_settings_svc.

All tests hit a real SQLite test DB (via the shared db_session fixture from
conftest.py). No mocks of the DB layer are used.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.models.platform_setting import PlatformSetting
from fleet_platform.services import platform_settings_svc as svc

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _delete_key(db: AsyncSession, key: str) -> None:
    """Remove a PlatformSetting row if it exists, so each test starts clean."""
    from sqlalchemy import delete
    await db.execute(delete(PlatformSetting).where(PlatformSetting.key == key))
    await db.commit()


# ---------------------------------------------------------------------------
# Test 1: get_setting returns None when key is absent
# ---------------------------------------------------------------------------

async def test_get_setting_returns_none_when_absent(db_session: AsyncSession):
    key = "integration_test_absent_key"
    await _delete_key(db_session, key)

    result = await svc.get_setting(db_session, key)

    assert result is None


# ---------------------------------------------------------------------------
# Test 2: set_setting creates a new row; get_setting retrieves it
# ---------------------------------------------------------------------------

async def test_set_and_get_setting_roundtrip(db_session: AsyncSession):
    key = "integration_test_plain_key"
    await _delete_key(db_session, key)

    await svc.set_setting(db_session, key, "hello_world")
    result = await svc.get_setting(db_session, key)

    assert result == "hello_world"

    # cleanup
    await _delete_key(db_session, key)


# ---------------------------------------------------------------------------
# Test 3: set_setting with encrypt=True stores ciphertext; get_setting
#          returns plaintext
# ---------------------------------------------------------------------------

async def test_set_setting_encrypted_stores_ciphertext_returns_plaintext(
    db_session: AsyncSession,
):
    key = "integration_test_encrypted_key"
    plaintext = "my-super-secret"
    await _delete_key(db_session, key)

    await svc.set_setting(db_session, key, plaintext, encrypt=True)

    # Verify the raw DB row holds ciphertext, not plaintext
    from sqlalchemy import select
    row_result = await db_session.execute(
        select(PlatformSetting).where(PlatformSetting.key == key)
    )
    row = row_result.scalar_one_or_none()
    assert row is not None
    assert row.is_encrypted is True
    assert row.value != plaintext  # stored as ciphertext

    # get_setting transparently decrypts
    retrieved = await svc.get_setting(db_session, key)
    assert retrieved == plaintext

    # cleanup
    await _delete_key(db_session, key)


# ---------------------------------------------------------------------------
# Test 4: set_setting called twice on same key updates the row, no duplicate
# ---------------------------------------------------------------------------

async def test_set_setting_updates_existing_row(db_session: AsyncSession):
    key = "integration_test_upsert_key"
    await _delete_key(db_session, key)

    await svc.set_setting(db_session, key, "first_value")
    await svc.set_setting(db_session, key, "second_value")

    result = await svc.get_setting(db_session, key)
    assert result == "second_value"

    # Confirm only one row exists
    from sqlalchemy import func, select
    count_result = await db_session.execute(
        select(func.count()).where(PlatformSetting.key == key)
    )
    count = count_result.scalar_one()
    assert count == 1

    # cleanup
    await _delete_key(db_session, key)


# ---------------------------------------------------------------------------
# Test 5: seed_settings_from_env inserts a row when env var set and row absent
# ---------------------------------------------------------------------------

async def test_seed_settings_from_env_inserts_when_absent(db_session: AsyncSession):
    key = svc.KRI_API_URL
    await _delete_key(db_session, key)

    with pytest.MonkeyPatch().context() as mp:
        mp.setenv("KRI_API_URL", "http://kri.test:8000")
        await svc.seed_settings_from_env(db_session)

    result = await svc.get_setting(db_session, key)
    assert result == "http://kri.test:8000"

    # cleanup
    await _delete_key(db_session, key)


# ---------------------------------------------------------------------------
# Test 6: seed_settings_from_env does NOT overwrite an existing row
# ---------------------------------------------------------------------------

async def test_seed_settings_from_env_does_not_overwrite_existing(
    db_session: AsyncSession,
):
    key = svc.KRI_API_URL
    await _delete_key(db_session, key)

    # Pre-populate the row with a user-configured value
    await svc.set_setting(db_session, key, "http://kri.production:8000")

    with pytest.MonkeyPatch().context() as mp:
        mp.setenv("KRI_API_URL", "http://kri.env-override:8000")
        await svc.seed_settings_from_env(db_session)

    result = await svc.get_setting(db_session, key)
    # Must still be the original value — env must not overwrite
    assert result == "http://kri.production:8000"

    # cleanup
    await _delete_key(db_session, key)


# ---------------------------------------------------------------------------
# Test 7: encrypt_secret / decrypt_secret roundtrip
# ---------------------------------------------------------------------------

def test_encrypt_decrypt_secret_roundtrip():
    plaintext = "s3cr3t-v@lue-123!"
    ciphertext = svc.encrypt_secret(plaintext)

    # Ciphertext is a different string
    assert ciphertext != plaintext
    # Fernet tokens are URL-safe base64 strings, not plaintext
    assert "s3cr3t" not in ciphertext

    recovered = svc.decrypt_secret(ciphertext)
    assert recovered == plaintext
