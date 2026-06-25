# fleet_platform/api/routes/ansible/files.py
"""Playbook file management routes: /files/..."""

from pathlib import Path

from fastapi import Body, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.api.deps import get_db
from fleet_platform.core.audit import audit
from fleet_platform.core.auth import require_role
from fleet_platform.models.platform_setting import PlatformSetting
from fleet_platform.services.playbook_sources import get_all_playbook_dirs

from ._router import _PLAYBOOKS_DIR, router


@router.get("/files")
async def list_playbook_files(
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("operator", "admin")),
):
    """Return the full recursive file tree of the playbooks directory."""
    from fleet_platform.services.platform_settings_svc import get_playbooks_dir

    playbooks_dir = await get_playbooks_dir(db)

    def _walk(path: Path, rel: str = "") -> list[dict]:
        items: list[dict] = []
        try:
            entries = sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name))
        except PermissionError:
            return items
        for entry in entries:
            entry_rel = f"{rel}/{entry.name}".lstrip("/")
            if entry.name.startswith(".") or entry.name == "__pycache__":
                continue
            if entry.is_dir():
                items.append(
                    {
                        "name": entry.name,
                        "path": entry_rel,
                        "type": "dir",
                        "children": _walk(entry, entry_rel),
                    }
                )
            else:
                items.append(
                    {
                        "name": entry.name,
                        "path": entry_rel,
                        "type": "file",
                        "size": entry.stat().st_size,
                        "ext": entry.suffix.lstrip("."),
                    }
                )
        return items

    return {"root": str(playbooks_dir), "tree": _walk(playbooks_dir)}


@router.get("/files/content")
async def get_playbook_file(
    path: str = Query(..., description="Absolute or relative path of the file"),
    source_dir: str | None = Query(None, description="Absolute source directory for relative paths"),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("viewer", "operator", "admin")),
):
    """Return the content of a file in any configured playbooks directory."""
    result = await db.execute(select(PlatformSetting).where(PlatformSetting.key == "playbook_sources"))
    setting = result.scalar_one_or_none()
    sources_json = setting.value if setting else None

    all_dirs = get_all_playbook_dirs(sources_json, _PLAYBOOKS_DIR)
    allowed_roots = [str(d.resolve()) for d in all_dirs]

    # Resolve: if path is relative, use source_dir or builtin dir as base
    if not Path(path).is_absolute():
        base = Path(source_dir) if source_dir else _PLAYBOOKS_DIR
        target = (base / path).resolve()
    else:
        target = Path(path).resolve()

    # Security: must be inside one of the allowed source dirs
    if not any(target.is_relative_to(Path(r)) for r in allowed_roots):
        raise HTTPException(status_code=400, detail="Path not in any configured playbook source")
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    try:
        content = target.read_text(errors="replace")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"path": str(target), "content": content, "size": target.stat().st_size}


@router.put("/files/content")
async def update_playbook_file(
    path: str = Query(..., description="Absolute or relative path of the file"),
    source_dir: str | None = Query(None, description="Absolute source directory for relative paths"),
    payload: dict = Body(...),
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_role("admin")),
):
    """Write content to a file in any configured playbooks directory. Admin only."""
    result = await db.execute(select(PlatformSetting).where(PlatformSetting.key == "playbook_sources"))
    setting = result.scalar_one_or_none()
    sources_json = setting.value if setting else None

    all_dirs = get_all_playbook_dirs(sources_json, _PLAYBOOKS_DIR)
    allowed_roots = [str(d.resolve()) for d in all_dirs]

    # Resolve: if path is relative, use source_dir or builtin dir as base
    if not Path(path).is_absolute():
        base = Path(source_dir) if source_dir else _PLAYBOOKS_DIR
        target = (base / path).resolve()
    else:
        target = Path(path).resolve()

    # Security: must be inside one of the allowed source dirs
    if not any(target.is_relative_to(Path(r)) for r in allowed_roots):
        raise HTTPException(status_code=400, detail="Path not in any configured playbook source")
    content = payload.get("content", "")
    if not isinstance(content, str):
        raise HTTPException(status_code=422, detail="content must be a string")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    await audit(
        db,
        actor=claims["email"],
        action="playbook_file.update",
        resource_type="playbook_file",
        new_value={"path": str(target)},
    )
    await db.commit()
    return {"path": str(target), "size": target.stat().st_size, "saved": True}
