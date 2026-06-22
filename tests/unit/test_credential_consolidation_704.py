"""Unit tests for the credential-consolidation epic (#704).

Covers the point-of-use guard (#701) and the inline-write bridge (#725).
The resolver FK behaviour (#698/#699) is covered in
``test_credential_resolver*.py``.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.services.credential_resolver import has_usable_secret
from fleet_platform.services.platform_settings_svc import decrypt_secret, encrypt_secret
from fleet_platform.services.ssh_credential_link import upsert_owner_ssh_credential

# ---------------------------------------------------------------------------
# #701 — has_usable_secret
# ---------------------------------------------------------------------------


def test_has_usable_secret_password():
    assert has_usable_secret({"auth_mode": "password", "ssh_password": "pw"}) is True
    assert has_usable_secret({"auth_mode": "password", "ssh_password": ""}) is False


def test_has_usable_secret_key():
    assert has_usable_secret({"auth_mode": "key", "ssh_key": "KEY"}) is True
    assert has_usable_secret({"auth_mode": "key", "ssh_key": ""}) is False


def test_has_usable_secret_global_no_secret():
    """Global fallback with no configured password is not usable."""
    assert has_usable_secret({"auth_mode": "password", "ssh_password": "", "credential_source": "global"}) is False


# ---------------------------------------------------------------------------
# #725 — upsert_owner_ssh_credential
# ---------------------------------------------------------------------------


def _name_free_db():
    """AsyncMock db whose _unique_name lookup reports the name as free."""
    db = AsyncMock(spec=AsyncSession)
    result = MagicMock()
    result.first.return_value = None  # name not taken
    db.execute.return_value = result
    return db


async def test_upsert_noop_when_nothing_provided():
    db = AsyncMock(spec=AsyncSession)
    cur = uuid.uuid4()
    out = await upsert_owner_ssh_credential(db, owner_name="node:n1", current_credential_id=cur)
    assert out == cur
    db.add.assert_not_called()


async def test_upsert_creates_password_credential():
    db = _name_free_db()
    out = await upsert_owner_ssh_credential(
        db,
        owner_name="node:n1",
        current_credential_id=None,
        ssh_username="admin",
        ssh_password="s3cret",
    )
    assert out is not None
    db.add.assert_called_once()
    cred = db.add.call_args[0][0]
    assert cred.name == "node:n1"
    assert cred.kind == "username_password"
    assert cred.username == "admin"
    assert decrypt_secret(cred.secret_enc) == "s3cret"
    db.flush.assert_awaited()


async def test_upsert_creates_key_credential():
    db = _name_free_db()
    out = await upsert_owner_ssh_credential(
        db,
        owner_name="group:prod",
        current_credential_id=None,
        ssh_username="deploy",
        ssh_key="PRIVATE_KEY",
        ssh_auth_mode="key",
    )
    assert out is not None
    cred = db.add.call_args[0][0]
    assert cred.kind == "ssh_key"
    assert decrypt_secret(cred.secret_enc) == "PRIVATE_KEY"


async def test_upsert_updates_existing_dedicated_credential():
    """A partial update merges with the existing dedicated credential in place."""
    existing = MagicMock()
    existing.id = uuid.uuid4()
    existing.name = "node:n1"
    existing.kind = "username_password"
    existing.username = "admin"
    existing.secret_enc = encrypt_secret("oldpw")

    db = AsyncMock(spec=AsyncSession)
    db.get.return_value = existing

    # Only the password changes; username is carried over from the existing row.
    out = await upsert_owner_ssh_credential(
        db,
        owner_name="node:n1",
        current_credential_id=existing.id,
        ssh_password="newpw",
    )
    assert out == existing.id
    assert existing.username == "admin"
    assert decrypt_secret(existing.secret_enc) == "newpw"
    db.add.assert_not_called()  # updated in place, not a new row


async def test_upsert_ignores_shared_credential_and_creates_new():
    """If the current FK points at a shared (differently-named) credential, don't mutate it."""
    shared = MagicMock()
    shared.id = uuid.uuid4()
    shared.name = "shared:team-key"  # not the owner's dedicated name
    shared.kind = "username_password"

    db = _name_free_db()
    db.get.return_value = shared

    out = await upsert_owner_ssh_credential(
        db,
        owner_name="node:n1",
        current_credential_id=shared.id,
        ssh_username="admin",
        ssh_password="pw",
    )
    assert out is not None
    assert out != shared.id
    db.add.assert_called_once()  # a fresh dedicated credential was created
