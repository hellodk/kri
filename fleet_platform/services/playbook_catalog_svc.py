"""Service functions for playbook curation — enable/disable/favorites/auto-disable."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.models.playbook_catalog import PlaybookCatalog, PlaybookFavorite


async def enable_playbook(
    db: AsyncSession,
    *,
    source_key: str,
    source_label: str,
    filename: str,
    entry_type: str,
    actor: str,
) -> PlaybookCatalog:
    """Upsert a catalog row with enabled=True using ON CONFLICT to prevent TOCTOU races."""
    now = datetime.now(UTC)
    stmt = (
        pg_insert(PlaybookCatalog)
        .values(
            source_key=source_key,
            source_label=source_label,
            filename=filename,
            entry_type=entry_type,
            enabled=True,
            enabled_by=actor,
            enabled_at=now,
            auto_disabled_at=None,
        )
        .on_conflict_do_update(
            index_elements=["source_key", "filename"],
            set_={
                "enabled": True,
                "source_label": source_label,
                "enabled_by": actor,
                "enabled_at": now,
                "auto_disabled_at": None,
            },
        )
        .returning(PlaybookCatalog)
    )
    result = await db.execute(stmt)
    row = result.scalar_one()
    return row


async def disable_playbook(
    db: AsyncSession,
    *,
    catalog_id: uuid.UUID,
    actor: str,
) -> PlaybookCatalog | None:
    """Set enabled=False on a catalog row. Row kept for history."""
    result = await db.execute(select(PlaybookCatalog).where(PlaybookCatalog.id == catalog_id))
    row = result.scalar_one_or_none()
    if row is None:
        return None
    row.enabled = False
    row.enabled_by = None
    row.enabled_at = None
    return row


async def enable_source(
    db: AsyncSession,
    *,
    source_key: str,
    source_label: str,
    discovered: list[dict],
    actor: str,
) -> int:
    """Bulk-enable all playbooks from a source. Returns count of newly enabled rows."""
    count = 0
    now = datetime.now(UTC)
    for entry in discovered:
        result = await db.execute(
            select(PlaybookCatalog).where(
                PlaybookCatalog.source_key == source_key,
                PlaybookCatalog.filename == entry["filename"],
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            row = PlaybookCatalog(
                source_key=source_key,
                source_label=source_label,
                filename=entry["filename"],
                entry_type=entry["entry_type"],
                enabled=True,
                enabled_by=actor,
                enabled_at=now,
            )
            db.add(row)
            count += 1
        elif not row.enabled:
            row.enabled = True
            row.enabled_by = actor
            row.enabled_at = now
            row.auto_disabled_at = None
            count += 1
    return count


async def auto_disable_missing(
    db: AsyncSession,
    *,
    source_key: str,
    discovered_filenames: set[str],
) -> list[PlaybookCatalog]:
    """Disable catalog rows for a source whose files are no longer discovered."""
    result = await db.execute(
        select(PlaybookCatalog).where(
            PlaybookCatalog.source_key == source_key,
            PlaybookCatalog.enabled == True,  # noqa: E712
        )
    )
    enabled_rows = result.scalars().all()
    now = datetime.now(UTC)
    disabled: list[PlaybookCatalog] = []
    for row in enabled_rows:
        if row.filename not in discovered_filenames:
            row.enabled = False
            row.auto_disabled_at = now
            disabled.append(row)
    return disabled


async def get_enabled(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
) -> list[dict]:
    """Return all enabled catalog rows annotated with is_favorite for the given user."""
    catalog_result = await db.execute(
        select(PlaybookCatalog).where(PlaybookCatalog.enabled == True)  # noqa: E712
    )
    rows = catalog_result.scalars().all()

    fav_result = await db.execute(select(PlaybookFavorite.catalog_id).where(PlaybookFavorite.user_id == user_id))
    fav_ids: set[uuid.UUID] = set(fav_result.scalars().all())

    return [
        {
            "catalog_id": row.id,
            "source_key": row.source_key,
            "source_label": row.source_label,
            "filename": row.filename,
            "entry_type": row.entry_type,
            "is_favorite": row.id in fav_ids,
        }
        for row in rows
    ]


async def get_library(db: AsyncSession) -> dict[tuple[str, str], dict]:
    """Return all catalog rows keyed by (source_key, filename)."""
    result = await db.execute(select(PlaybookCatalog))
    rows = result.scalars().all()
    return {
        (row.source_key, row.filename): {
            "enabled": row.enabled,
            "catalog_id": row.id,
            "auto_disabled_at": row.auto_disabled_at,
        }
        for row in rows
    }


async def add_favorite(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    catalog_id: uuid.UUID,
) -> None:
    """Add a favorite — idempotent."""
    result = await db.execute(
        select(PlaybookFavorite).where(
            PlaybookFavorite.user_id == user_id,
            PlaybookFavorite.catalog_id == catalog_id,
        )
    )
    if result.scalar_one_or_none() is None:
        db.add(PlaybookFavorite(user_id=user_id, catalog_id=catalog_id))


async def remove_favorite(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    catalog_id: uuid.UUID,
) -> None:
    """Remove a favorite — silent if not found."""
    result = await db.execute(
        select(PlaybookFavorite).where(
            PlaybookFavorite.user_id == user_id,
            PlaybookFavorite.catalog_id == catalog_id,
        )
    )
    row = result.scalar_one_or_none()
    if row is not None:
        await db.delete(row)
