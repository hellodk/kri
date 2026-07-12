"""Read/write helpers for the ``credential_groups`` association (#985 Phase 2b).

Phase 2a (resolver, #984) made resolution prefer ``credential_groups`` over the
legacy ``Group.credential_id`` column. This phase moves the *write* path (group
credential PATCH) and the credential reference-count reads onto the same
association, so ``credential_groups`` becomes the source of truth for both
reads and writes while ``Group.credential_id`` is kept (unwritten) for
expand-contract safety — it is dropped in a later phase.

One credential per group is enforced by ``UNIQUE(group_id)`` on
``credential_groups`` (migration 065). :func:`set_group_credential` performs an
idempotent delete-then-insert upsert so callers never hit a unique-violation.
"""

from __future__ import annotations

import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.models.credential_group import CredentialGroup
from fleet_platform.models.group import GroupMember


async def set_group_credential(db: AsyncSession, group_id: uuid.UUID, credential_id: uuid.UUID | None) -> None:
    """Set (or clear) the single credential mapped to ``group_id``.

    Deletes any existing ``credential_groups`` row for ``group_id`` first, then
    inserts a new one if ``credential_id`` is not ``None``. Idempotent w.r.t.
    the ``UNIQUE(group_id)`` constraint. Does not commit — the caller commits.
    """
    await db.execute(delete(CredentialGroup).where(CredentialGroup.group_id == group_id))
    if credential_id is not None:
        db.add(CredentialGroup(credential_id=credential_id, group_id=group_id))


async def get_group_credential_id(db: AsyncSession, group_id: uuid.UUID) -> uuid.UUID | None:
    """Return the credential_id mapped to ``group_id``, or ``None`` if unmapped."""
    result = await db.execute(select(CredentialGroup.credential_id).where(CredentialGroup.group_id == group_id))
    return result.scalar_one_or_none()


async def count_groups_for_credential(db: AsyncSession, credential_id: uuid.UUID) -> int:
    """Return the number of groups mapped to ``credential_id`` via ``credential_groups``."""
    result = await db.execute(
        select(func.count()).select_from(CredentialGroup).where(CredentialGroup.credential_id == credential_id)
    )
    return result.scalar_one()


async def count_nodes_for_credential(db: AsyncSession, credential_id: uuid.UUID) -> int:
    """Return the number of distinct nodes in groups mapped to ``credential_id``.

    Joins ``group_members -> credential_groups`` on ``group_id``.
    """
    result = await db.execute(
        select(func.count(func.distinct(GroupMember.node_id)))
        .select_from(GroupMember)
        .join(CredentialGroup, CredentialGroup.group_id == GroupMember.group_id)
        .where(CredentialGroup.credential_id == credential_id)
    )
    return result.scalar_one()
