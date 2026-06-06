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


def _dir_source_pairs(sources_json: str | None) -> list[tuple[Path, str, str]]:
    """Return list of (directory, source_key, source_label) for all present sources.

    Built-in dir is always first. Each configured source is paired with its
    key/label directly from the source config — no index arithmetic so absent
    directories never shift mappings (Fix #446).
    """
    from fleet_platform.services.playbook_sources import get_all_playbook_dirs  # local import to avoid circularity

    sources = _parse_sources(sources_json)
    all_dirs = get_all_playbook_dirs(sources_json, _PLAYBOOKS_DIR)

    pairs: list[tuple[Path, str, str]] = []
    # The built-in dir (index 0 from get_all_playbook_dirs) is always _PLAYBOOKS_DIR if it exists.
    # We track which dirs came from which source by matching against source configs.
    builtin_claimed = False
    remaining_dirs = list(all_dirs)

    # First dir is always builtin when _PLAYBOOKS_DIR is present in the list.
    if remaining_dirs and remaining_dirs[0] == _PLAYBOOKS_DIR:
        pairs.append((_PLAYBOOKS_DIR, str(_PLAYBOOKS_DIR), "built-in"))
        remaining_dirs = remaining_dirs[1:]
        builtin_claimed = True
    elif remaining_dirs and not builtin_claimed:
        # _PLAYBOOKS_DIR was not present (absent dir skipped) — first dir might still be builtin
        # but since get_all_playbook_dirs always starts with builtin_dir regardless, the first
        # element is always builtin. Handle that case too.
        pass

    # Match remaining dirs to sources in order — sources whose dirs are absent were already
    # skipped by get_all_playbook_dirs, so there is a 1-1 correspondence between remaining_dirs
    # and sources that had present directories.
    dir_iter = iter(remaining_dirs)
    for src in sources:
        src_type = src.get("type", "local")
        if src_type == "local":
            raw = src.get("path", "")
            from fleet_platform.services.playbook_sources import _translate_path

            translated_path = Path(_translate_path(raw))
            if translated_path.is_dir():
                d = next(dir_iter, None)
                if d is not None:
                    sk = src.get("path") or str(d)
                    sl = src.get("label") or sk.split("/")[-1]
                    pairs.append((d, sk, sl))
        elif src_type == "git":
            from fleet_platform.services.playbook_sources import _default_clone_path

            local = src.get("local_path") or _default_clone_path(src["url"])
            if Path(local).is_dir():
                d = next(dir_iter, None)
                if d is not None:
                    sk = src.get("url") or str(d)
                    sl = src.get("label") or sk.rstrip("/").split("/")[-1].replace(".git", "")
                    pairs.append((d, sk, sl))

    return pairs


@router.get("", response_model=list[PlaybookLibraryEntryResponse])
async def list_library(
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("operator", "admin")),
):
    """Return all discovered playbooks annotated with their catalog state."""
    sources_json = await _get_sources_json(db)
    catalog_map = await get_library(db)

    results: list[PlaybookLibraryEntryResponse] = []
    for d, source_key, source_label in _dir_source_pairs(sources_json):
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

    discovered: list[dict] = []
    source_label = payload.source_key.split("/")[-1].replace(".git", "")

    for d, sk, sl in _dir_source_pairs(sources_json):
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
    await db.commit()
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
    await db.commit()
    return {"catalog_id": str(catalog_id), "favorited": False}
