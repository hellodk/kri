"""Bridge inline SSH credential input onto the first-class Credential store (#725).

Before the credential-consolidation epic (#704), node/group SSH creds were
written straight into inline ``ssh_*`` columns. Those columns are now a
deprecated read-fallback; all *writes* go through a dedicated ``Credential``
row referenced by ``owner.credential_id``.

These helpers let the existing API request shape (``ssh_username`` /
``ssh_password`` / ``ssh_key`` / ``ssh_auth_mode``) keep working: the inline
fields are transparently upserted into the owner's dedicated credential
(named ``node:<minion_id>`` / ``group:<name>``) instead of the inline columns.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.models.credential import Credential
from fleet_platform.services.platform_settings_svc import decrypt_secret, encrypt_secret


async def _unique_name(db: AsyncSession, base: str) -> str:
    exists = (await db.execute(select(Credential.id).where(Credential.name == base).limit(1))).first()
    return base if not exists else f"{base}-{uuid.uuid4().hex[:8]}"


async def upsert_owner_ssh_credential(
    db: AsyncSession,
    *,
    owner_name: str,
    current_credential_id: uuid.UUID | None,
    ssh_username: str | None = None,
    ssh_password: str | None = None,
    ssh_key: str | None = None,
    ssh_auth_mode: str | None = None,
) -> uuid.UUID | None:
    """Create or update the owner's dedicated SSH credential; return its id.

    ``owner_name`` is the canonical credential name (e.g. ``node:<minion_id>``).
    Partial updates merge with the existing dedicated credential referenced by
    ``current_credential_id`` (only when that credential's name matches
    ``owner_name`` — shared credentials are never mutated here). Returns the
    credential id for the caller to assign to ``owner.credential_id``, or
    ``current_credential_id`` unchanged when there's nothing to store.
    """
    if ssh_username is None and ssh_password is None and ssh_key is None and ssh_auth_mode is None:
        return current_credential_id

    existing: Credential | None = None
    if current_credential_id is not None:
        cred = await db.get(Credential, current_credential_id)
        if cred is not None and cred.name == owner_name:
            existing = cred

    auth_mode = ssh_auth_mode or (("key" if existing.kind == "ssh_key" else "password") if existing else "password")
    is_key = auth_mode == "key"

    def _existing_secret() -> str:
        if not existing or not existing.secret_enc:
            return ""
        existing_is_key = existing.kind == "ssh_key"
        if existing_is_key != is_key:
            return ""  # auth mode flipped — don't carry the wrong secret type over
        try:
            return decrypt_secret(existing.secret_enc)
        except Exception:
            return ""

    if is_key:
        secret_plain = ssh_key if ssh_key is not None else _existing_secret()
    else:
        secret_plain = ssh_password if ssh_password is not None else _existing_secret()

    username = ssh_username if ssh_username is not None else (existing.username if existing else None)

    # Never manufacture a secret-less credential (#704/#701). A username with no
    # password/key is not a usable SSH credential — creating one would link the
    # owner to a dead FK that resolves to the "no usable credential" guard and
    # short-circuits group/controller/global fallback. With no existing dedicated
    # row to update, leave the owner unlinked so resolution can fall through.
    if existing is None and not secret_plain:
        return current_credential_id

    kind = "ssh_key" if is_key else "username_password"
    secret_enc = encrypt_secret(secret_plain) if secret_plain else ""

    if existing is not None:
        existing.kind = kind
        existing.username = username
        existing.secret_enc = secret_enc
        return existing.id

    cred = Credential(
        id=uuid.uuid4(),
        name=await _unique_name(db, owner_name),
        kind=kind,
        username=username,
        secret_enc=secret_enc,
        description="Managed inline SSH credential (#725)",
    )
    db.add(cred)
    await db.flush()
    return cred.id


async def owner_secret_flags(
    db: AsyncSession,
    *,
    credential_id: uuid.UUID | None,
    inline_password_enc: str | None,
    inline_key_enc: str | None,
) -> tuple[bool, bool]:
    """Return ``(has_password, has_key)`` for an owner, credential-aware.

    Prefers the linked Credential; falls back to the inline columns when no FK
    is set (one-release read-fallback).
    """
    if credential_id is not None:
        cred = await db.get(Credential, credential_id)
        if cred is not None:
            has_secret = bool(cred.secret_enc)
            if cred.kind == "ssh_key":
                return (False, has_secret)
            return (has_secret, False)
    return (bool(inline_password_enc), bool(inline_key_enc))
