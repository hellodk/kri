"""Playbook library curation endpoints — enable/disable and favorites."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.api.deps import get_db
from fleet_platform.core.audit import audit
from fleet_platform.core.auth import get_current_user, require_role
from fleet_platform.models.platform_setting import PlatformSetting
from fleet_platform.models.playbook_catalog import PlaybookCatalog
from fleet_platform.schemas.playbook import (
    PlaybookCatalogDisableRequest,
    PlaybookCatalogEnableRequest,
    PlaybookCatalogEnableSourceRequest,
    PlaybookLibraryEntryResponse,
)
from fleet_platform.services.playbook_catalog_svc import (
    add_favorite,
    disable_playbook,
    enable_playbook,
    enable_source,
    get_library,
    remove_favorite,
)
from fleet_platform.services.playbook_discovery import discover_all
from fleet_platform.services.playbook_sources import get_all_playbook_dirs

_PLAYBOOKS_DIR = Path("/app/playbooks")

router = APIRouter(prefix="/api/v1/ansible/playbooks/library", tags=["playbook-library"])


async def _get_sources_json(db: AsyncSession) -> str | None:
    result = await db.execute(select(PlatformSetting).where(PlatformSetting.key == "playbook_sources"))
    setting = result.scalar_one_or_none()
    return setting.value if setting else None


def _parse_sources(sources_json: str | None) -> list[dict]:
    if not sources_json:
        return []
    try:
        return json.loads(sources_json)
    except (ValueError, TypeError):
        return []


@router.get("", response_model=list[PlaybookLibraryEntryResponse])
async def list_library(
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("operator", "admin")),
):
    """Return all discovered playbooks annotated with their catalog state."""
    sources_json = await _get_sources_json(db)
    sources = _parse_sources(sources_json)
    all_dirs = get_all_playbook_dirs(sources_json, _PLAYBOOKS_DIR)
    catalog_map = await get_library(db)

    results: list[PlaybookLibraryEntryResponse] = []
    for i, d in enumerate(all_dirs):
        if i == 0:
            source_key = str(d)
            source_label = "built-in"
        else:
            src = sources[i - 1]
            source_key = src.get("url") or src.get("path") or str(d)
            source_label = src.get("label") or source_key.split("/")[-1].replace(".git", "")

        for entry in discover_all(d):
            catalog_info = catalog_map.get((source_key, entry.filename), {})
            results.append(
                PlaybookLibraryEntryResponse(
                    filename=entry.filename,
                    name=entry.name,
                    description=entry.description,
                    entry_type=entry.entry_type,
                    default_vars=entry.default_vars,
                    var_descriptions=entry.var_descriptions,
                    lint_errors=entry.lint_errors,
                    source_dir=str(d),
                    source_key=source_key,
                    source_label=source_label,
                    enabled=catalog_info.get("enabled", False),
                    catalog_id=catalog_info.get("catalog_id"),
                    auto_disabled_at=catalog_info.get("auto_disabled_at"),
                )
            )
    return results


@router.post("/enable", status_code=200)
async def enable_library_entry(
    payload: PlaybookCatalogEnableRequest,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_role("admin")),
):
    """Enable a playbook — creates or updates its catalog row."""
    result = await db.execute(
        select(PlaybookCatalog).where(
            PlaybookCatalog.source_key == payload.source_key,
            PlaybookCatalog.filename == payload.filename,
        )
    )
    existing = result.scalar_one_or_none()
    old_value = {"enabled": existing.enabled} if existing else {"enabled": False}

    row = await enable_playbook(
        db,
        source_key=payload.source_key,
        source_label=payload.source_label,
        filename=payload.filename,
        entry_type=payload.entry_type,
        actor=claims["email"],
    )
    await audit(
        db,
        actor=claims["email"],
        action="playbook.enable",
        resource_type="playbook_catalog",
        resource_id=row.id,
        old_value=old_value,
        new_value={"enabled": True, "filename": payload.filename, "source": payload.source_label},
    )
    await db.commit()
    return {"id": str(row.id), "enabled": True}


@router.post("/disable", status_code=200)
async def disable_library_entry(
    payload: PlaybookCatalogDisableRequest,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_role("admin")),
):
    """Disable a playbook — sets enabled=False, row is kept."""
    result = await db.execute(select(PlaybookCatalog).where(PlaybookCatalog.id == payload.catalog_id))
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Catalog entry not found")

    await disable_playbook(db, catalog_id=payload.catalog_id, actor=claims["email"])
    await audit(
        db,
        actor=claims["email"],
        action="playbook.disable",
        resource_type="playbook_catalog",
        resource_id=payload.catalog_id,
        old_value={"enabled": True},
        new_value={"enabled": False},
    )
    await db.commit()
    return {"id": str(payload.catalog_id), "enabled": False}


@router.post("/enable-source", status_code=200)
async def enable_source_entries(
    payload: PlaybookCatalogEnableSourceRequest,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_role("admin")),
):
    """Bulk-enable all discovered playbooks from a source."""
    sources_json = await _get_sources_json(db)
    sources = _parse_sources(sources_json)
    all_dirs = get_all_playbook_dirs(sources_json, _PLAYBOOKS_DIR)

    discovered: list[dict] = []
    source_label = payload.source_key.split("/")[-1].replace(".git", "")

    for i, d in enumerate(all_dirs):
        if i == 0:
            sk = str(d)
            sl = "built-in"
        else:
            src = sources[i - 1]
            sk = src.get("url") or src.get("path") or str(d)
            sl = src.get("label") or sk.split("/")[-1].replace(".git", "")
        if sk == payload.source_key:
            source_label = sl
            for entry in discover_all(d):
                discovered.append({"filename": entry.filename, "entry_type": entry.entry_type})
            break

    count = await enable_source(
        db,
        source_key=payload.source_key,
        source_label=source_label,
        discovered=discovered,
        actor=claims["email"],
    )
    await audit(
        db,
        actor=claims["email"],
        action="playbook.enable_source",
        resource_type="playbook_source",
        resource_id=None,
        old_value=None,
        new_value={"source_key": payload.source_key, "count": count},
    )
    await db.commit()
    return {"source_key": payload.source_key, "enabled_count": count}


@router.post("/favorites/{catalog_id}", status_code=201)
async def add_favorite_entry(
    catalog_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(get_current_user),
):
    """Star a playbook as a personal favorite."""
    result = await db.execute(select(PlaybookCatalog).where(PlaybookCatalog.id == catalog_id))
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Catalog entry not found")

    user_id = uuid.UUID(claims["sub"])
    await add_favorite(db, user_id=user_id, catalog_id=catalog_id)
    return {"catalog_id": str(catalog_id), "favorited": True}


@router.delete("/favorites/{catalog_id}", status_code=200)
async def remove_favorite_entry(
    catalog_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(get_current_user),
):
    """Remove a personal favorite."""
    user_id = uuid.UUID(claims["sub"])
    await remove_favorite(db, user_id=user_id, catalog_id=catalog_id)
    return {"catalog_id": str(catalog_id), "favorited": False}
