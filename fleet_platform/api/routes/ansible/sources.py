# fleet_platform/api/routes/ansible/sources.py
"""Playbook sources routes: /sources/..."""

import asyncio
import subprocess
from pathlib import Path

from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.api.deps import get_db
from fleet_platform.core.audit import audit
from fleet_platform.core.auth import require_role
from fleet_platform.models.platform_setting import PlatformSetting
from fleet_platform.schemas.playbook import (
    PlaybookEntryResponse,
    PlaybookSourceRequest,
    PlaybookSourceResponse,
    PlaybookSourcesImportRequest,
    PlaybookSourceSyncResult,
    PlaybookSourceValidateRequest,
    PlaybookSourceValidateResponse,
)
from fleet_platform.services.git_auth import classify_git_error, git_auth_env, redact_secrets
from fleet_platform.services.platform_settings_svc import decrypt_secret, encrypt_secret
from fleet_platform.services.playbook_discovery import discover_all
from fleet_platform.services.playbook_sources import sync_all_git_sources

from ._router import router


@router.get("/sources", response_model=list[PlaybookSourceResponse])
async def list_sources(
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("viewer", "operator", "admin")),
):
    """List configured extra playbook sources."""
    import json as _json

    result = await db.execute(select(PlatformSetting).where(PlatformSetting.key == "playbook_sources"))
    setting = result.scalar_one_or_none()
    if not setting or not setting.value:
        return []
    try:
        sources = _json.loads(setting.value)
    except (ValueError, TypeError):
        return []
    return [PlaybookSourceResponse(index=i, **{k: v for k, v in src.items()}) for i, src in enumerate(sources)]


@router.post("/sources/validate", response_model=PlaybookSourceValidateResponse)
async def validate_source(
    payload: PlaybookSourceValidateRequest,
    _: dict = Depends(require_role("operator", "admin")),
):
    """Validate a playbook source without saving it. Returns scan results."""
    import os

    warnings: list[str] = []
    logs: list[str] = []

    if payload.type == "local":
        if not payload.path:
            return PlaybookSourceValidateResponse(valid=False, error="path is required for local source", logs=logs)

        logs.append("[1/2] Checking path...")
        path = Path(payload.path).expanduser().resolve()

        if not path.exists():
            logs.append(f"[1/2] ✗ Path does not exist: {path}")
            return PlaybookSourceValidateResponse(valid=False, error=f"Path does not exist: {path}", logs=logs)
        if not path.is_dir():
            logs.append(f"[1/2] ✗ Not a directory: {path}")
            return PlaybookSourceValidateResponse(valid=False, error=f"Not a directory: {path}", logs=logs)
        if not os.access(path, os.R_OK | os.X_OK):
            logs.append(f"[1/2] ✗ Directory is not readable: {path}")
            return PlaybookSourceValidateResponse(valid=False, error=f"Directory is not readable: {path}", logs=logs)
        logs.append(f"[1/2] ✓ Path exists and is readable: {path}")

        logs.append("[2/2] Scanning for Ansible playbooks and roles...")
        try:
            entries = await asyncio.to_thread(discover_all, path)
        except Exception as e:
            logs.append(f"[2/2] ✗ Scan failed: {e}")
            return PlaybookSourceValidateResponse(valid=False, error=f"Scan failed: {e}", logs=logs)

        if not entries:
            warnings.append("No playbooks or roles found in this directory.")
            logs.append("[2/2] ⚠ No playbooks or roles found in this directory.")
        else:
            playbooks = [e for e in entries if e.entry_type == "playbook"]
            roles = [e for e in entries if e.entry_type == "role"]
            logs.append(f"[2/2] ✓ Found {len(playbooks)} playbooks, {len(roles)} roles")

        playbooks = [e for e in entries if e.entry_type == "playbook"]
        roles = [e for e in entries if e.entry_type == "role"]
        return PlaybookSourceValidateResponse(
            valid=True,
            warnings=warnings,
            playbook_count=len(playbooks),
            role_count=len(roles),
            logs=logs,
            entries=[
                PlaybookEntryResponse(
                    filename=e.filename,
                    name=e.name,
                    description=e.description,
                    entry_type=e.entry_type,
                    default_vars=e.default_vars,
                    lint_errors=e.lint_errors,
                )
                for e in entries
            ],
        )

    elif payload.type == "git":
        if not payload.url:
            return PlaybookSourceValidateResponse(valid=False, error="url is required for git source", logs=logs)

        import logging as _logging

        _log = _logging.getLogger(__name__)

        raw_url = payload.url.strip()
        branch = payload.branch or "main"

        # Resolve credentials: stored Credential row > inline token/ssh_key (back-compat)
        token: str | None = None
        ssh_key: str | None = None

        if payload.credential_id:
            import uuid as _uuid

            from fleet_platform.models.credential import Credential as _Credential

            try:
                _cred_uuid = _uuid.UUID(payload.credential_id)
            except ValueError:
                return PlaybookSourceValidateResponse(valid=False, error="Invalid credential_id format.", logs=logs)
            # Resolve via async DB session — inject via a separate dependency would
            # require signature change; we rely on the outer async session from the
            # route that owns this request.  Use a fresh session to keep it simple.
            from fleet_platform.db.session import AsyncSessionLocal as _ASL

            async with _ASL() as _cred_db:
                _res = await _cred_db.execute(select(_Credential).where(_Credential.id == _cred_uuid))
                _cred = _res.scalar_one_or_none()
            if _cred is None:
                return PlaybookSourceValidateResponse(
                    valid=False, error=f"Credential {payload.credential_id!r} not found.", logs=logs
                )
            if _cred.kind in ("token", "username_password"):
                token = decrypt_secret(_cred.secret_enc)
            elif _cred.kind == "ssh_key":
                ssh_key = decrypt_secret(_cred.secret_enc)
            # Update last_used_at asynchronously (fire and forget)
            from datetime import UTC as _UTC
            from datetime import datetime as _datetime

            from fleet_platform.db.session import AsyncSessionLocal as _ASL2

            async def _touch_cred() -> None:
                async with _ASL2() as _db2:
                    _r = await _db2.execute(select(_Credential).where(_Credential.id == _cred_uuid))
                    _c = _r.scalar_one_or_none()
                    if _c:
                        _c.last_used_at = _datetime.now(_UTC)
                        await _db2.commit()

            asyncio.create_task(_touch_cred())
        else:
            token = payload.token
            ssh_key = payload.ssh_key

        import tempfile as _tmpfile

        with git_auth_env(token=token, ssh_key=ssh_key) as _git_env:
            # Step 1: ls-remote — fast, non-destructive connectivity check
            logs.append("[1/3] Testing connectivity to repository...")
            if token:
                logs.append("[1/3] Authenticating with personal access token...")
            elif ssh_key:
                logs.append("[1/3] Authenticating with SSH key...")

            try:
                ls_result = await asyncio.to_thread(
                    lambda: subprocess.run(
                        ["git", "ls-remote", "--exit-code", "--heads", raw_url, f"refs/heads/{branch}"],
                        capture_output=True,
                        timeout=20,
                        env=_git_env,
                    )
                )
                if ls_result.returncode != 0:
                    # Branch might exist but ls-remote filtering missed it — try without filter
                    ls_result2 = await asyncio.to_thread(
                        lambda: subprocess.run(
                            ["git", "ls-remote", "--exit-code", raw_url],
                            capture_output=True,
                            timeout=20,
                            env=_git_env,
                        )
                    )
                    if ls_result2.returncode != 0:
                        raw_err = ls_result2.stderr.decode(errors="replace").strip()
                        err = redact_secrets(raw_err, [token, ssh_key])
                        kind = classify_git_error(raw_err)
                        if kind == "auth_required":
                            logs.append("[1/3] ✗ Repository requires authentication (private, or not found)")
                            _log.warning("[validate] auth_required for %s", raw_url)
                            return PlaybookSourceValidateResponse(
                                valid=False,
                                error=(
                                    "Repository requires authentication — it is private or does not exist anonymously"
                                ),
                                auth_required=True,
                                error_kind=kind,
                                logs=logs,
                            )
                        elif kind == "unreachable":
                            logs.append(f"[1/3] ✗ Host unreachable: {err}")
                            return PlaybookSourceValidateResponse(
                                valid=False,
                                error="Host unreachable — check the URL/network",
                                error_kind=kind,
                                logs=logs,
                            )
                        else:
                            msg = err or "connection refused or repo not found"
                            logs.append(f"[1/3] ✗ Cannot access repository: {msg}")
                            return PlaybookSourceValidateResponse(
                                valid=False,
                                error=f"Cannot access git repository: {msg}",
                                error_kind=kind,
                                logs=logs,
                            )
                    warnings.append(f"Branch '{branch}' not found — will use default branch.")
                    logs.append(f"[1/3] ⚠ Branch '{branch}' not found — will use default branch")
                    branch = "HEAD"
                else:
                    logs.append("[1/3] ✓ Repository reachable")
            except Exception as e:
                logs.append(f"[1/3] ✗ git ls-remote failed: {e}")
                return PlaybookSourceValidateResponse(valid=False, error=f"git ls-remote failed: {e}", logs=logs)

            # Step 2: shallow clone to temp dir and scan
            logs.append("[2/3] Shallow clone (depth=1)...")
            with _tmpfile.TemporaryDirectory(prefix="kri-validate-") as tmpdir:
                clone_cmd = ["git", "clone", "--depth=1", "--single-branch"]
                if branch != "HEAD":
                    clone_cmd += ["--branch", branch]
                clone_cmd += [raw_url, tmpdir]

                try:
                    clone_result = await asyncio.to_thread(
                        lambda: subprocess.run(clone_cmd, capture_output=True, timeout=60, env=_git_env)
                    )
                    if clone_result.returncode != 0:
                        raw_err = clone_result.stderr.decode(errors="replace").strip()
                        err = redact_secrets(raw_err, [token, ssh_key])
                        kind = classify_git_error(raw_err)
                        logs.append(f"[2/3] ✗ Clone failed: {err[:200]}")
                        return PlaybookSourceValidateResponse(
                            valid=False,
                            error=f"Clone failed: {err[:300]}",
                            error_kind=kind,
                            logs=logs,
                        )
                    logs.append("[2/3] ✓ Clone complete")
                except Exception as e:
                    logs.append(f"[2/3] ✗ Clone error: {e}")
                    return PlaybookSourceValidateResponse(valid=False, error=f"Clone error: {e}", logs=logs)

                logs.append("[3/3] Scanning for Ansible playbooks and roles...")
                try:
                    entries = await asyncio.to_thread(discover_all, Path(tmpdir))
                except Exception as e:
                    logs.append(f"[3/3] ✗ Scan failed: {e}")
                    return PlaybookSourceValidateResponse(valid=False, error=f"Scan failed: {e}", logs=logs)

            playbooks = [e for e in entries if e.entry_type == "playbook"]
            roles = [e for e in entries if e.entry_type == "role"]

            if not entries:
                warnings.append("No playbooks or roles found in this repository.")
                logs.append("[3/3] ⚠ No playbooks or roles found in this repository.")
            else:
                logs.append(f"[3/3] ✓ Found {len(playbooks)} playbooks, {len(roles)} roles")

            return PlaybookSourceValidateResponse(
                valid=True,
                warnings=warnings,
                playbook_count=len(playbooks),
                role_count=len(roles),
                logs=logs,
                entries=[
                    PlaybookEntryResponse(
                        filename=e.filename,
                        name=e.name,
                        description=e.description,
                        entry_type=e.entry_type,
                        default_vars=e.default_vars,
                        lint_errors=e.lint_errors,
                    )
                    for e in entries
                ],
            )

    return PlaybookSourceValidateResponse(valid=False, error=f"Unknown source type: {payload.type}", logs=logs)


@router.post("/sources", response_model=PlaybookSourceResponse, status_code=201)
async def add_source(
    payload: PlaybookSourceRequest,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_role("operator", "admin")),
):
    """Add a new playbook source (local directory or git repository)."""
    import json as _json
    import os

    if payload.type == "local":
        if not payload.path:
            raise HTTPException(status_code=422, detail="path is required for local source")
        p = Path(payload.path).expanduser().resolve()
        if not p.exists():
            raise HTTPException(status_code=422, detail=f"Path does not exist: {p}")
        if not p.is_dir():
            raise HTTPException(status_code=422, detail=f"Not a directory: {p}")
        if not os.access(p, os.R_OK | os.X_OK):
            raise HTTPException(status_code=422, detail=f"Directory is not readable: {p}")
    elif payload.type == "git":
        if not payload.url:
            raise HTTPException(status_code=422, detail="url is required for git source")
        raw_url = payload.url.strip()

        # Resolve credentials for the ls-remote access check
        _add_token: str | None = None
        _add_ssh_key: str | None = None
        if payload.credential_id:
            import uuid as _uuid_mod

            from fleet_platform.models.credential import Credential as _Cred

            try:
                _cred_uuid = _uuid_mod.UUID(payload.credential_id)
            except ValueError:
                raise HTTPException(status_code=422, detail="Invalid credential_id format.")
            _cr = await db.execute(select(_Cred).where(_Cred.id == _cred_uuid))
            _c = _cr.scalar_one_or_none()
            if _c is None:
                raise HTTPException(status_code=404, detail=f"Credential {payload.credential_id!r} not found.")
            if _c.kind in ("token", "username_password"):
                _add_token = decrypt_secret(_c.secret_enc)
            elif _c.kind == "ssh_key":
                _add_ssh_key = decrypt_secret(_c.secret_enc)
        else:
            _add_token = payload.token
            _add_ssh_key = payload.ssh_key

        with git_auth_env(token=_add_token, ssh_key=_add_ssh_key) as _git_env:
            ls = await asyncio.to_thread(
                lambda: subprocess.run(
                    ["git", "ls-remote", "--exit-code", raw_url],
                    capture_output=True,
                    timeout=20,
                    env=_git_env,
                )
            )
        if ls.returncode != 0:
            raw_err = ls.stderr.decode(errors="replace").strip()
            err = redact_secrets(raw_err, [_add_token, _add_ssh_key])
            detail = f"Cannot access git repository: {err[:200] or 'connection refused'}"
            raise HTTPException(status_code=422, detail=detail)

    result = await db.execute(select(PlatformSetting).where(PlatformSetting.key == "playbook_sources"))
    setting = result.scalar_one_or_none()
    sources = []
    if setting and setting.value:
        try:
            sources = _json.loads(setting.value)
        except (ValueError, TypeError):
            sources = []

    new_src: dict = {"type": payload.type}
    if payload.type == "local":
        new_src["path"] = payload.path
    elif payload.type == "git":
        new_src["url"] = payload.url
        new_src["branch"] = payload.branch
        if payload.local_path:
            new_src["local_path"] = payload.local_path
        if payload.credential_id:
            # Prefer credential reference over inline secrets
            new_src["credential_id"] = payload.credential_id
        else:
            if payload.token:
                new_src["token_enc"] = encrypt_secret(payload.token)
            if payload.ssh_key:
                new_src["ssh_key_enc"] = encrypt_secret(payload.ssh_key)
    if payload.label:
        new_src["label"] = payload.label

    sources.append(new_src)
    new_index = len(sources) - 1

    if setting:
        setting.value = _json.dumps(sources)
    else:
        setting = PlatformSetting(key="playbook_sources", value=_json.dumps(sources))
        db.add(setting)
    await audit(
        db,
        actor=claims["email"],
        action="playbook_source.create",
        resource_type="playbook_source",
        new_value={"type": payload.type, "index": new_index, "label": payload.label},
    )
    await db.commit()

    # For git sources: clone in the background so the repo appears immediately
    # in the Playbooks tab without requiring a manual Sync click.
    if payload.type == "git":
        from fleet_platform.services.playbook_sources import _clone_git_source, _default_clone_path

        assert payload.url is not None, "git source requires a URL"  # noqa: S101
        local_path: str = payload.local_path or _default_clone_path(payload.url)
        asyncio.create_task(
            asyncio.to_thread(
                _clone_git_source,
                payload.url,
                payload.branch or "main",
                local_path,
                token=_add_token if payload.type == "git" else None,
                ssh_key=_add_ssh_key if payload.type == "git" else None,
            )
        )

    return PlaybookSourceResponse(index=new_index, **new_src)


@router.delete("/sources/{index}", status_code=204)
async def remove_source(
    index: int,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_role("operator", "admin")),
):
    """Remove a playbook source by its index."""
    import json as _json

    result = await db.execute(select(PlatformSetting).where(PlatformSetting.key == "playbook_sources"))
    setting = result.scalar_one_or_none()
    if not setting or not setting.value:
        raise HTTPException(status_code=404, detail="No sources configured")
    try:
        sources = _json.loads(setting.value)
    except (ValueError, TypeError):
        raise HTTPException(status_code=500, detail="Corrupt sources setting")
    if index < 0 or index >= len(sources):
        raise HTTPException(status_code=404, detail=f"Source index {index} not found")
    removed = sources.pop(index)
    setting.value = _json.dumps(sources)
    await audit(
        db,
        actor=claims["email"],
        action="playbook_source.delete",
        resource_type="playbook_source",
        new_value={"index": index, "type": removed.get("type")},
    )
    await db.commit()


@router.post("/sources/sync", response_model=PlaybookSourceSyncResult)
async def sync_sources(
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_role("operator", "admin")),
):
    """Force-sync all configured git playbook sources (runs git pull in a thread)."""
    import asyncio as _asyncio
    import json as _json

    from fleet_platform.services.playbook_catalog_svc import auto_disable_missing

    result = await db.execute(select(PlatformSetting).where(PlatformSetting.key == "playbook_sources"))
    setting = result.scalar_one_or_none()
    sources_json = setting.value if setting else None
    # Run blocking git pull in a thread so we don't stall the async event loop
    sync_results = await _asyncio.to_thread(sync_all_git_sources, sources_json)

    # Auto-disable catalog entries whose files were removed from synced sources
    _sources_list: list[dict] = []
    if sources_json:
        try:
            _sources_list = _json.loads(sources_json)
        except (ValueError, TypeError):
            pass

    # Fix #496: build per-source identity map so absent dirs don't corrupt the
    # positional mapping. zip(extra_dirs, _sources_list) is still wrong when an
    # earlier source dir is absent — extra_dirs is shorter, causing source N+1's
    # dir to be paired with source N's metadata. Use is_dir() per source instead.
    from fleet_platform.services.playbook_sources import (
        _default_clone_path as _dcp,
    )
    from fleet_platform.services.playbook_sources import (
        _translate_path as _tp,
    )

    for src in _sources_list:
        src_type = src.get("type", "local")
        source_key = src.get("url") or src.get("path") or ""
        if not source_key:
            continue
        if src_type == "local":
            raw = src.get("path", "")
            translated = _tp(raw)
            d = Path(translated)
            if not d.is_dir():
                continue
        elif src_type == "git":
            url = src.get("url", "")
            if not url:
                continue
            local_path = src.get("local_path") or _dcp(url)
            d = Path(local_path)
            if not d.is_dir():
                continue
        else:
            continue
        discovered_filenames = {e.filename for e in discover_all(d)}
        disabled = await auto_disable_missing(db, source_key=source_key, discovered_filenames=discovered_filenames)
        for row in disabled:
            await audit(
                db,
                actor="system",
                action="playbook.auto_disable",
                resource_type="playbook_catalog",
                resource_id=row.id,
                new_value={"enabled": False, "reason": "source file removed", "filename": row.filename},
            )

    await audit(
        db,
        actor=claims["email"],
        action="playbook_source.sync",
        resource_type="playbook_source",
        new_value={"sources_synced": len(sync_results)},
    )
    await db.commit()
    return PlaybookSourceSyncResult(results=sync_results)


@router.post("/sources/import", response_model=dict)
async def import_sources_csv(
    payload: PlaybookSourcesImportRequest,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_role("operator", "admin")),
):
    """Bulk-import playbook sources from CSV text.

    Format (one entry per line):
        type, path/url, branch (for git; leave blank for local), label
    Lines starting with '#' are treated as comments and ignored.
    """
    import json as _json

    result = await db.execute(select(PlatformSetting).where(PlatformSetting.key == "playbook_sources"))
    setting = result.scalar_one_or_none()
    sources: list[dict] = []
    if setting and setting.value:
        try:
            sources = _json.loads(setting.value)
        except (ValueError, TypeError):
            sources = []

    added = 0
    for raw_line in payload.csv.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 2:
            continue
        src_type = parts[0].lower()
        if src_type not in ("local", "git"):
            continue
        new_src: dict = {"type": src_type}
        if src_type == "local":
            new_src["path"] = parts[1]
        elif src_type == "git":
            new_src["url"] = parts[1]
            new_src["branch"] = parts[2] if len(parts) > 2 and parts[2] else "main"
        if len(parts) > 3 and parts[3]:
            new_src["label"] = parts[3]
        sources.append(new_src)
        added += 1

    if setting:
        setting.value = _json.dumps(sources)
    else:
        setting = PlatformSetting(key="playbook_sources", value=_json.dumps(sources))
        db.add(setting)
    if added:
        await audit(
            db,
            actor=claims["email"],
            action="playbook_source.bulk_import",
            resource_type="playbook_source",
            new_value={"added": added},
        )
        await db.commit()

    return {"added": added}
