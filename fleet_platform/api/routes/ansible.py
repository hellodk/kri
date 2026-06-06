# fleet_platform/api/routes/ansible.py
import asyncio
import re
import secrets
import subprocess
import uuid
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.api.deps import get_db
from fleet_platform.api.limiter import limiter
from fleet_platform.core.audit import audit
from fleet_platform.core.auth import get_current_user, hash_password, require_role
from fleet_platform.models.ansible_job import AnsibleJob
from fleet_platform.models.node import Node
from fleet_platform.models.platform_setting import PlatformSetting
from fleet_platform.schemas.ansible import BootstrapRequest, BootstrapResponse
from fleet_platform.schemas.playbook import (
    AnsibleJobResponse,
    PlaybookEntryResponse,
    PlaybookRunRequest,
    PlaybookRunResponse,
    PlaybookSourceRequest,
    PlaybookSourceResponse,
    PlaybookSourcesImportRequest,
    PlaybookSourceSyncResult,
    PlaybookSourceValidateRequest,
    PlaybookSourceValidateResponse,
)
from fleet_platform.services.credential_resolver import node_has_group
from fleet_platform.services.git_auth import classify_git_error, git_auth_env, redact_secrets
from fleet_platform.services.log_delta import slice_from, split_running_marker
from fleet_platform.services.platform_settings_svc import decrypt_secret, encrypt_secret
from fleet_platform.services.playbook_discovery import discover_all
from fleet_platform.services.playbook_sources import get_all_playbook_dirs, sync_all_git_sources
from fleet_platform.workers.ansible_tasks import bootstrap_node
from fleet_platform.workers.playbook_tasks import run_playbook

router = APIRouter(prefix="/api/v1/ansible")

_MINION_ID_RE = re.compile(r"^[a-zA-Z0-9._-]{1,128}$")
_PLAYBOOKS_DIR = Path(__file__).parent.parent.parent.parent / "playbooks"

_SENSITIVE_EV_KEYS = frozenset(
    {
        "ansible_ssh_pass",
        "ansible_become_password",
        "ansible_become_pass",
        "ansible_password",
        "ansible_sudo_pass",
        "vault_password",
        "password",
        "secret",
        "token",
        "api_key",
    }
)


def _scrub_extravars(ev: dict | list | None) -> dict | list | None:
    """Recursively scrub sensitive keys from extravars (flat dict, nested dict, or list)."""
    if isinstance(ev, dict):
        return {k: "***" if k.lower() in _SENSITIVE_EV_KEYS else _scrub_extravars(v) for k, v in ev.items()}
    if isinstance(ev, list):
        return [_scrub_extravars(item) for item in ev]
    return ev


@router.post("/bootstrap", response_model=BootstrapResponse, status_code=202)
@limiter.limit("10/minute")
async def bootstrap(
    request: Request,
    payload: BootstrapRequest,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_role("operator", "admin")),
):
    if not _MINION_ID_RE.match(payload.minion_id):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid minion_id '{payload.minion_id}': only [a-zA-Z0-9._-] allowed",
        )

    result = await db.execute(select(Node).where(Node.minion_id == payload.minion_id))
    node = result.scalar_one_or_none()

    if node and node.bootstrap_status == "bootstrapping":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Node is already being bootstrapped",
        )

    placeholder_token = secrets.token_urlsafe(32)

    if node is None:
        node = Node(
            minion_id=payload.minion_id,
            hostname=payload.minion_id.split(".")[0],
            ip_address=payload.target_ip,
            status="unknown",
            drift_score=0,
            node_token_hash=hash_password(placeholder_token),
            first_seen_at=datetime.now(UTC),
            bootstrap_status="pending",
            bootstrap_ip=payload.target_ip,
        )
        db.add(node)
        await db.flush()
        await db.commit()
        await db.refresh(node)
    else:
        node.bootstrap_status = "pending"
        node.bootstrap_ip = payload.target_ip
        node.bootstrap_logs = ""  # clear previous run's logs
        node.bootstrap_error = None  # clear previous error

    # Enforce: node must belong to at least one group before bootstrapping
    if not await node_has_group(node.id, db):
        raise HTTPException(
            status_code=400,
            detail="Node must belong to at least one group before bootstrapping. "
            "Add the node to a group first, then configure group SSH credentials.",
        )

    # Save SSH credentials to the node for future reuse
    if payload.ssh_username:
        node.ssh_username = payload.ssh_username
    if payload.ssh_password:
        node.ssh_password_enc = encrypt_secret(payload.ssh_password)
        node.ssh_auth_mode = "password"
    elif payload.ssh_key:
        node.ssh_key_enc = encrypt_secret(payload.ssh_key)
        node.ssh_auth_mode = "key"
    await audit(
        db,
        actor=claims["email"],
        action="node.bootstrap.request",
        resource_type="node",
        resource_id=node.id,
        new_value={"minion_id": node.minion_id, "target_ip": payload.target_ip},
    )
    await db.commit()
    await db.refresh(node)

    task = bootstrap_node.delay(
        str(node.id),
        payload.target_ip,
        ssh_username=payload.ssh_username,
    )

    return BootstrapResponse(
        node_id=node.id,
        minion_id=node.minion_id,
        job_id=task.id,
        bootstrap_status="pending",
        message="Bootstrap queued. Node will appear in fleet once Salt minion connects.",
    )


@router.get("/bootstrap/{node_id}/status")
async def bootstrap_status(
    node_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("operator", "admin")),
):
    from datetime import UTC, datetime, timedelta  # noqa: PLC0415

    from fleet_platform.models.bootstrap_run import BootstrapRun  # noqa: PLC0415

    result = await db.execute(select(Node).where(Node.id == node_id))
    node = result.scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")

    # Auto-heal: if node is stuck in 'bootstrapping' but all bootstrap runs
    # for it have terminal status, reset to 'failed' so the UI doesn't hang.
    if node.bootstrap_status == "bootstrapping":
        stale_cutoff = datetime.now(UTC) - timedelta(minutes=15)
        runs = await db.execute(
            select(BootstrapRun)
            .where(BootstrapRun.node_id == node_id)
            .order_by(BootstrapRun.started_at.desc())
            .limit(1)
        )
        latest_run = runs.scalar_one_or_none()
        is_stale = (
            latest_run is None
            or latest_run.status in ("completed", "failed")
            or (latest_run.finished_at is None and latest_run.started_at < stale_cutoff)
        )
        if is_stale:
            node.bootstrap_status = "failed"
            node.bootstrap_error = "Bootstrap timed out or state was lost — use Cancel Bootstrap to reset."
            await db.commit()

    return {
        "node_id": str(node.id),
        "minion_id": node.minion_id,
        "bootstrap_status": node.bootstrap_status,
        "bootstrap_ip": node.bootstrap_ip,
        "bootstrap_error": node.bootstrap_error,
    }


@router.post("/bootstrap/{node_id}/cancel")
async def cancel_bootstrap(
    node_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_role("operator", "admin")),
):
    """Reset a stuck bootstrap job so the node can be re-bootstrapped."""
    result = await db.execute(select(Node).where(Node.id == node_id))
    node = result.scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    if node.bootstrap_status not in ("bootstrapping", "pending"):
        raise HTTPException(
            status_code=409,
            detail=f"Bootstrap status is '{node.bootstrap_status}' — nothing to cancel",
        )
    node.bootstrap_status = "failed"
    node.bootstrap_error = "Manually cancelled by user"
    await audit(
        db,
        actor=claims["email"],
        action="node.bootstrap.cancel",
        resource_type="node",
        resource_id=node.id,
        new_value={"minion_id": node.minion_id},
    )
    await db.commit()
    return {"node_id": str(node.id), "bootstrap_status": "failed", "message": "Bootstrap cancelled"}


@router.get("/bootstrap/{node_id}/logs")
async def bootstrap_logs(
    node_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("operator", "admin")),
):
    result = await db.execute(select(Node).where(Node.id == node_id))
    node = result.scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")

    return {
        "node_id": str(node.id),
        "minion_id": node.minion_id,
        "bootstrap_status": node.bootstrap_status,
        "ansible_stdout": node.bootstrap_logs,
    }


@router.get("/bootstrap/{node_id}/history")
async def bootstrap_history(
    node_id: uuid.UUID,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("viewer", "operator", "admin")),
):
    """List all bootstrap runs for a node, newest first."""
    from sqlalchemy import desc

    from fleet_platform.models.bootstrap_run import BootstrapRun

    result = await db.execute(
        select(BootstrapRun)
        .where(BootstrapRun.node_id == node_id)
        .order_by(desc(BootstrapRun.started_at))
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    runs = result.scalars().all()

    total = await db.scalar(
        select(func.count()).select_from(select(BootstrapRun).where(BootstrapRun.node_id == node_id).subquery())
    )

    return {
        "items": [
            {
                "id": str(r.id),
                "started_at": r.started_at.isoformat(),
                "finished_at": r.finished_at.isoformat() if r.finished_at else None,
                "target_ip": r.target_ip,
                "status": r.status,
                "error": r.error,
                "has_stdout": bool(r.ansible_stdout),
            }
            for r in runs
        ],
        "total": total or 0,
        "page": page,
        "per_page": per_page,
    }


@router.get("/bootstrap/{node_id}/history/{run_id}")
async def bootstrap_run_detail(
    node_id: uuid.UUID,
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("viewer", "operator", "admin")),
):
    """Return full logs for a specific bootstrap run."""
    from fleet_platform.models.bootstrap_run import BootstrapRun

    result = await db.execute(
        select(BootstrapRun).where(
            BootstrapRun.id == run_id,
            BootstrapRun.node_id == node_id,
        )
    )
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    return {
        "id": str(run.id),
        "node_id": str(run.node_id),
        "started_at": run.started_at.isoformat(),
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "target_ip": run.target_ip,
        "status": run.status,
        "ansible_stdout": run.ansible_stdout,
        "error": run.error,
    }


@router.get("/playbooks", response_model=list[PlaybookEntryResponse])
async def list_playbooks(
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_role("viewer", "operator", "admin")),
):
    import json as _json
    import uuid as _uuid

    from fleet_platform.services.playbook_catalog_svc import get_enabled

    # Fix #460: guard against missing sub claim
    _sub = claims.get("sub")
    if not _sub:
        raise HTTPException(status_code=401, detail="Missing user identity in token")
    user_id = _uuid.UUID(_sub)

    # Load sources_json early so it's available for legacy fallback below
    result = await db.execute(select(PlatformSetting).where(PlatformSetting.key == "playbook_sources"))
    setting = result.scalar_one_or_none()
    sources_json = setting.value if setting else None

    sources: list[dict] = []
    if sources_json:
        try:
            sources = _json.loads(sources_json)
        except (ValueError, TypeError):
            sources = []

    enabled = await get_enabled(db, user_id=user_id)
    if not enabled:
        # Fix #447/#503: legacy fallback when no enabled entries exist — covers
        # both "catalog never configured" (catalog_total == 0) and "catalog has
        # rows but all disabled" (catalog_total > 0, enabled empty).
        # Previously guarded by catalog_total == 0 which silently returned []
        # when all entries were disabled — fixed by always falling back here.
        all_dirs_legacy = get_all_playbook_dirs(sources_json, _PLAYBOOKS_DIR)
        legacy_entries = []
        for d in all_dirs_legacy:
            for e in discover_all(d):
                legacy_entries.append(
                    PlaybookEntryResponse(
                        filename=e.filename,
                        name=e.name,
                        description=e.description,
                        entry_type=e.entry_type,
                        default_vars=e.default_vars,
                        lint_errors=e.lint_errors,
                        source_dir=str(d),
                        catalog_id=None,
                        is_favorite=False,
                    )
                )
        return legacy_entries

    # Fix #496: build a per-source identity map (source_key → dir) so that absent
    # source dirs do not corrupt the positional mapping between sources and dirs.
    # get_all_playbook_dirs skips absent dirs, making it shorter than sources[];
    # using positional index (i - 1) into sources[] was therefore wrong.
    from fleet_platform.services.playbook_sources import (
        _default_clone_path,
        _translate_path,
    )

    # Build source_key → resolved_dir for each configured source (mirroring
    # get_all_playbook_dirs logic) but keyed by identity, not position.
    source_dir_map: dict[str, Path] = {}
    for src in sources:
        src_type = src.get("type", "local")
        source_key = src.get("url") or src.get("path") or ""
        if not source_key:
            continue
        if src_type == "local":
            raw = src.get("path", "")
            translated = _translate_path(raw)
            p = Path(translated)
            if p.is_dir():
                source_dir_map[source_key] = p
        elif src_type == "git":
            url = src.get("url", "")
            if not url:
                continue
            local_path = src.get("local_path") or _default_clone_path(url)
            p = Path(local_path)
            if p.is_dir():
                source_dir_map[source_key] = p

    catalog_lookup: dict[tuple[str, str], dict] = {(e["source_key"], e["filename"]): e for e in enabled}

    all_entries: list[PlaybookEntryResponse] = []

    # Built-in dir (always index 0 in get_all_playbook_dirs)
    builtin_key = str(_PLAYBOOKS_DIR)
    for e in discover_all(_PLAYBOOKS_DIR):
        info = catalog_lookup.get((builtin_key, e.filename))
        if info is None:
            continue
        all_entries.append(
            PlaybookEntryResponse(
                filename=e.filename,
                name=e.name,
                description=e.description,
                entry_type=e.entry_type,
                default_vars=e.default_vars,
                lint_errors=e.lint_errors,
                source_dir=builtin_key,
                catalog_id=info["catalog_id"],
                is_favorite=info["is_favorite"],
            )
        )

    # Per-source dirs — keyed by identity, not position
    for source_key, d in source_dir_map.items():
        for e in discover_all(d):
            info = catalog_lookup.get((source_key, e.filename))
            if info is None:
                continue
            all_entries.append(
                PlaybookEntryResponse(
                    filename=e.filename,
                    name=e.name,
                    description=e.description,
                    entry_type=e.entry_type,
                    default_vars=e.default_vars,
                    lint_errors=e.lint_errors,
                    source_dir=str(d),
                    catalog_id=info["catalog_id"],
                    is_favorite=info["is_favorite"],
                )
            )
    return all_entries


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


@router.get("/playbooks/content")
async def get_playbook_content(
    filename: str,
    _: dict = Depends(require_role("viewer", "operator", "admin")),
):
    """Return raw YAML content of a discovered playbook or role's main task file."""
    entries = discover_all(_PLAYBOOKS_DIR)
    entry = next((e for e in entries if e.filename == filename), None)
    if not entry:
        raise HTTPException(status_code=404, detail="Playbook not found")

    if entry.entry_type == "playbook":
        content_path = _PLAYBOOKS_DIR / filename
    else:
        # For roles: show tasks/main.yml
        role_name = filename.replace("roles/", "")
        content_path = _PLAYBOOKS_DIR / "roles" / role_name / "tasks" / "main.yml"

    if not content_path.exists():
        raise HTTPException(status_code=404, detail="Playbook file not found on disk")

    try:
        content = content_path.read_text()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not read playbook: {e}")

    return {"filename": filename, "content": content}


@router.get("/playbooks/tree")
async def get_playbook_tree(
    filename: str = Query(..., description="Playbook filename or role name"),
    source_dir: str | None = Query(None, description="Absolute source directory path"),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("viewer", "operator", "admin")),
):
    """Return the dependency tree of a playbook/role in execution order."""
    import yaml as _yaml

    result = await db.execute(select(PlatformSetting).where(PlatformSetting.key == "playbook_sources"))
    setting = result.scalar_one_or_none()
    sources_json = setting.value if setting else None

    # Find which directory contains this filename
    if source_dir:
        playbooks_dir = Path(source_dir)
    else:
        all_dirs = get_all_playbook_dirs(sources_json, _PLAYBOOKS_DIR)
        playbooks_dir = next(
            (d for d in all_dirs if (d / filename).exists() or (d / "roles" / filename.replace("roles/", "")).is_dir()),
            _PLAYBOOKS_DIR,
        )

    # Determine if this is a playbook file or a role directory
    playbook_path = playbooks_dir / filename
    roles_dir = playbooks_dir / "roles"

    def _file_node(rel_path: str, label: str, node_type: str, task_name: str | None = None) -> dict:
        abs_path = playbooks_dir / rel_path
        return {
            "type": node_type,
            "path": rel_path,
            "label": label,
            "exists": abs_path.exists(),
            "task_name": task_name,
        }

    def _walk_role(role_name: str) -> dict | None:
        role_path = roles_dir / role_name
        if not role_path.is_dir():
            return None

        children = []
        # Standard Ansible role directory order
        for subdir, node_type, label_prefix in [
            ("tasks", "tasks", "tasks/"),
            ("handlers", "handlers", "handlers/"),
            ("defaults", "defaults", "defaults/"),
            ("vars", "vars", "vars/"),
            ("templates", "template", "templates/"),
            ("files", "file", "files/"),
            ("meta", "meta", "meta/"),
        ]:
            subpath = role_path / subdir
            if subpath.is_dir():
                for f in sorted(subpath.iterdir()):
                    if f.is_file() and not f.name.startswith("."):
                        rel = str(f.relative_to(playbooks_dir))
                        children.append(_file_node(rel, f"{label_prefix}{f.name}", node_type))

        return {
            "type": "role",
            "path": f"roles/{role_name}",
            "label": role_name,
            "exists": True,
            "children": children,
        }

    def _extract_templates_from_tasks(tasks: list) -> list[dict]:
        """Find template: tasks and return the .j2 file references."""
        nodes = []
        if not isinstance(tasks, list):
            return nodes
        for task in tasks:
            if not isinstance(task, dict):
                continue
            task_name = task.get("name", "")
            # template module
            for key in ("template", "ansible.builtin.template"):
                tmpl = task.get(key)
                if isinstance(tmpl, dict):
                    src = tmpl.get("src", "")
                    if src:
                        # src is relative to role's templates/ or playbook's templates/
                        for candidate in [f"templates/{src}", src]:
                            if (playbooks_dir / candidate).exists():
                                nodes.append(_file_node(candidate, src, "template", task_name))
                                break
                        else:
                            nodes.append(_file_node(f"templates/{src}", src, "template", task_name))
            # include_tasks / import_tasks
            _task_include_keys = (
                "include_tasks",
                "import_tasks",
                "ansible.builtin.include_tasks",
                "ansible.builtin.import_tasks",
            )
            for key in _task_include_keys:
                inc = task.get(key)
                if isinstance(inc, str):
                    nodes.append(_file_node(inc, inc, "include", task_name))
                elif isinstance(inc, dict) and "file" in inc:
                    f = inc["file"]
                    nodes.append(_file_node(f, f, "include", task_name))
        return nodes

    nodes: list[dict] = []

    if playbook_path.exists() and playbook_path.is_file():
        # It's a playbook .yml file
        nodes.append(_file_node(filename, filename, "playbook"))

        try:
            with open(playbook_path) as f:
                plays = _yaml.safe_load(f) or []
        except Exception:
            plays = []

        seen_paths: set[str] = {filename}

        for play in plays if isinstance(plays, list) else []:
            if not isinstance(play, dict):
                continue

            # vars_files
            for vf in play.get("vars_files", []):
                if isinstance(vf, str) and vf not in seen_paths:
                    seen_paths.add(vf)
                    nodes.append(_file_node(vf, vf, "vars"))

            # roles
            for role in play.get("roles", []):
                role_name = role if isinstance(role, str) else role.get("role", role.get("name", ""))
                if role_name:
                    role_node = _walk_role(role_name)
                    if role_node:
                        nodes.append(role_node)

            # tasks (top-level)
            task_nodes = _extract_templates_from_tasks(play.get("tasks", []))
            for tn in task_nodes:
                if tn["path"] not in seen_paths:
                    seen_paths.add(tn["path"])
                    nodes.append(tn)

            # handlers
            for handler in play.get("handlers", []):
                pass  # inline handlers don't have separate files unless notify

    elif filename and not filename.endswith(".yml"):
        # Treat as a role name
        role_node = _walk_role(filename)
        if role_node:
            nodes.append(role_node)
        else:
            raise HTTPException(status_code=404, detail=f"Playbook or role '{filename}' not found")
    else:
        raise HTTPException(status_code=404, detail=f"Playbook '{filename}' not found")

    return {"filename": filename, "nodes": nodes}


@router.post("/playbooks/run", response_model=PlaybookRunResponse, status_code=202)
async def run_playbook_endpoint(
    payload: PlaybookRunRequest,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_role("operator", "admin")),
):
    # Use discover_all as the authoritative allowlist — only known playbooks/roles can run
    entries = discover_all(_PLAYBOOKS_DIR)
    entry = next((e for e in entries if e.filename == payload.playbook), None)
    if not entry:
        raise HTTPException(status_code=404, detail="Playbook not found")
    safe_name = entry.filename  # trusted — came from filesystem scan, not user input

    target_label = payload.target_id
    if payload.target_type == "node":
        node_result = await db.execute(select(Node).where(Node.id == uuid.UUID(payload.target_id)))
        node = node_result.scalar_one_or_none()
        if not node:
            raise HTTPException(status_code=404, detail="Node not found")
        target_label = node.hostname or node.minion_id
    elif payload.target_type == "group":
        from fleet_platform.models.group import Group

        grp_result = await db.execute(select(Group).where(Group.id == uuid.UUID(payload.target_id)))
        grp = grp_result.scalar_one_or_none()
        if not grp:
            raise HTTPException(status_code=404, detail="Group not found")
        target_label = grp.name

    job = AnsibleJob(
        playbook=safe_name,
        target_type=payload.target_type,
        target_id=payload.target_id,
        target_label=target_label,
        extravars=_scrub_extravars(payload.extravars) if payload.extravars else payload.extravars,
        verbosity=max(0, min(4, payload.verbosity or 0)),
        timeout_seconds=max(60, min(21600, payload.timeout_seconds)),
        status="pending",
        triggered_by=claims["sub"],
    )
    db.add(job)
    await db.flush()
    await audit(
        db,
        actor=claims["email"],
        action="playbook.run",
        resource_type="ansible_job",
        resource_id=job.id,
        new_value={"playbook": safe_name, "target_type": payload.target_type, "target_id": payload.target_id},
    )
    await db.commit()
    await db.refresh(job)

    task = run_playbook.delay(
        str(job.id),
        ssh_username=payload.ssh_username,
        verbosity=job.verbosity,
    )
    job.celery_task_id = task.id
    await db.commit()

    return PlaybookRunResponse(
        job_id=job.id,
        playbook=safe_name,
        target_label=target_label,
        status="pending",
        message="Playbook queued.",
    )


@router.post("/nodes/{node_id}/collect-grains", status_code=202)
async def collect_grains(
    node_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_role("operator", "admin")),
):
    """Trigger an Ansible run to collect grains from a live node and push to ingest."""
    from sqlalchemy import select as _sel

    result = await db.execute(_sel(Node).where(Node.id == node_id))
    node = result.scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    if not node.bootstrap_ip:
        raise HTTPException(status_code=400, detail="Node has no bootstrap_ip — run bootstrap first")

    from fleet_platform.workers.celery_app import celery_app

    task = celery_app.send_task(
        "fleet_platform.workers.ansible_tasks.collect_node_grains",
        args=[str(node_id)],
        queue="maintenance",
    )
    return {"task_id": task.id, "node_id": str(node_id), "status": "queued"}


@router.get("/jobs", response_model=list[AnsibleJobResponse])
async def list_ansible_jobs(
    status: str | None = Query(None, description="Filter by status: pending|running|completed|failed"),
    node_id: str | None = Query(None, description="Filter by target node UUID"),
    page: int = Query(1, ge=1),
    per_page: int = Query(25, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("viewer", "operator", "admin")),
):
    """List all ansible playbook jobs, newest first."""
    q = select(AnsibleJob).order_by(AnsibleJob.created_at.desc())
    if status:
        q = q.where(AnsibleJob.status == status)
    if node_id:
        # Include both direct-node jobs AND group jobs for groups this node belongs to
        try:
            node_uuid = uuid.UUID(node_id)
        except ValueError:
            raise HTTPException(status_code=422, detail="node_id must be a valid UUID")
        from sqlalchemy import or_

        from fleet_platform.models.group import GroupMember

        group_ids_result = await db.execute(select(GroupMember.group_id).where(GroupMember.node_id == node_uuid))
        group_ids = [str(gid) for gid in group_ids_result.scalars().all()]
        # Match: target_id == node_id (direct) OR target_id in group_ids (group run)
        conditions = [AnsibleJob.target_id == node_id]
        if group_ids:
            conditions.append(AnsibleJob.target_id.in_(group_ids))
        q = q.where(or_(*conditions))
    q = q.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(q)
    jobs = result.scalars().all()
    return [
        AnsibleJobResponse(
            id=j.id,
            playbook=j.playbook,
            target_type=j.target_type,
            target_label=j.target_label,
            target_id=str(j.target_id) if j.target_id else None,
            extravars=_scrub_extravars(j.extravars or {}) or {},  # type: ignore[arg-type]
            status=j.status,
            triggered_by=j.triggered_by,
            started_at=j.started_at,
            completed_at=j.completed_at,
            stdout=j.stdout,
            rc=j.rc,
            timeout_seconds=j.timeout_seconds,
            created_at=j.created_at,
            celery_task_id=j.celery_task_id,
            cancelled_at=j.cancelled_at,
        )
        for j in jobs
    ]


@router.get("/jobs/{job_id}", response_model=AnsibleJobResponse)
async def get_ansible_job(
    job_id: uuid.UUID,
    from_byte: int | None = Query(default=None, ge=0),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("viewer", "operator", "admin")),
):
    result = await db.execute(select(AnsibleJob).where(AnsibleJob.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    stdout_out: str | None
    total_len: int | None
    running: str | None
    if from_byte is not None:
        base, running = split_running_marker(job.stdout)
        stdout_out = slice_from(base, from_byte)
        total_len = len(base)
    else:
        stdout_out = job.stdout
        total_len = None
        running = None

    return AnsibleJobResponse(
        id=job.id,
        playbook=job.playbook,
        target_type=job.target_type,
        target_label=job.target_label,
        target_id=str(job.target_id) if job.target_id else None,
        extravars=_scrub_extravars(job.extravars or {}) or {},  # type: ignore[arg-type]
        status=job.status,
        triggered_by=job.triggered_by,
        started_at=job.started_at,
        completed_at=job.completed_at,
        stdout=stdout_out,
        rc=job.rc,
        verbosity=job.verbosity,
        timeout_seconds=job.timeout_seconds,
        created_at=job.created_at,
        celery_task_id=job.celery_task_id,
        cancelled_at=job.cancelled_at,
        stdout_total_len=total_len,
        running_task=running,
    )


@router.post("/jobs/{job_id}/cancel", status_code=200)
async def cancel_playbook_job(
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_role("operator", "admin")),
):
    """Cancel a running or pending playbook job (#342)."""
    from fleet_platform.workers.celery_app import celery_app as _celery

    result = await db.execute(select(AnsibleJob).where(AnsibleJob.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status not in ("running", "pending"):
        raise HTTPException(
            status_code=409,
            detail=f"Job is already in terminal state '{job.status}' — cannot cancel",
        )

    # Revoke the Celery task (SIGTERM to the worker process) — best-effort
    if job.celery_task_id:
        try:
            _celery.control.revoke(job.celery_task_id, terminate=True, signal="SIGTERM")
        except Exception:
            pass  # revoke is best-effort — DB update still proceeds

    now = datetime.now(UTC)
    job.status = "cancelled"
    job.completed_at = now
    job.cancelled_at = now
    existing_stdout = job.stdout or ""
    _actor = claims.get("email") or claims.get("sub", "unknown")
    job.stdout = (existing_stdout + f"\n\n[CANCELLED] Job manually cancelled by {_actor} at {now.isoformat()}").lstrip()

    await audit(
        db,
        actor=_actor,
        action="playbook_job_cancelled",
        resource_type="ansible_job",
        resource_id=job_id,
        new_value={"job_id": str(job_id), "playbook": job.playbook},
    )
    await db.commit()  # single commit covers status + audit

    return {"job_id": str(job_id), "status": "cancelled", "message": "Job cancelled successfully"}


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


@router.get("/playbooks/{playbook_name:path}/stats")
async def playbook_stats(
    playbook_name: str,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("operator", "admin")),
) -> dict:
    """Return duration statistics for the last 5 completed runs of a playbook."""
    rows = await db.execute(
        select(AnsibleJob)
        .where(
            AnsibleJob.playbook == playbook_name,
            AnsibleJob.status == "completed",
            AnsibleJob.started_at.is_not(None),
            AnsibleJob.completed_at.is_not(None),
        )
        .order_by(AnsibleJob.completed_at.desc())
        .limit(5)
    )
    jobs = rows.scalars().all()

    durations = []
    for j in jobs:
        if j.started_at and j.completed_at:
            secs = (j.completed_at - j.started_at).total_seconds()
            if secs > 0:
                durations.append(int(secs))

    if not durations:
        return {"playbook": playbook_name, "run_count": 0, "last_duration_seconds": None, "avg_duration_seconds": None}

    return {
        "playbook": playbook_name,
        "run_count": len(durations),
        "last_duration_seconds": durations[0],
        "avg_duration_seconds": int(sum(durations) / len(durations)),
    }


@router.get("/tasks/{task_id}")
async def get_task_status(
    task_id: str,
    _: dict = Depends(get_current_user),
):
    """Return Celery task state + result for any queued task."""
    from celery.result import AsyncResult

    from fleet_platform.workers.celery_app import celery_app

    result = AsyncResult(task_id, app=celery_app)
    payload: dict = {"task_id": task_id, "state": result.state}
    if result.ready():
        try:
            payload["result"] = result.result if not isinstance(result.result, Exception) else str(result.result)
        except Exception:
            payload["result"] = None
    return payload
