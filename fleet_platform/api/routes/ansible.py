# fleet_platform/api/routes/ansible.py
import re
import secrets
import subprocess
import uuid
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, status
from sqlalchemy import func

_MINION_ID_RE = re.compile(r'^[a-zA-Z0-9._-]{1,128}$')
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.api.deps import get_db
from fleet_platform.api.limiter import limiter
from fleet_platform.core.auth import get_current_user, hash_password, require_role
from fleet_platform.services.platform_settings_svc import encrypt_secret
from fleet_platform.models.ansible_job import AnsibleJob
from fleet_platform.models.node import Node
from fleet_platform.schemas.ansible import BootstrapRequest, BootstrapResponse
from fleet_platform.models.platform_setting import PlatformSetting
from fleet_platform.schemas.playbook import (
    AnsibleJobResponse,
    PlaybookEntryResponse,
    PlaybookRunRequest,
    PlaybookRunResponse,
    PlaybookSourceRequest,
    PlaybookSourceResponse,
    PlaybookSourceSyncResult,
    PlaybookSourceValidateRequest,
    PlaybookSourceValidateResponse,
    PlaybookSourcesImportRequest,
)
from fleet_platform.services.playbook_discovery import discover_all
from fleet_platform.services.playbook_sources import get_all_playbook_dirs, sync_all_git_sources
from fleet_platform.workers.ansible_tasks import bootstrap_node
from fleet_platform.workers.playbook_tasks import run_playbook
from fleet_platform.services.credential_resolver import node_has_group

router = APIRouter(prefix="/api/v1/ansible")

_PLAYBOOKS_DIR = Path(__file__).parent.parent.parent.parent / "playbooks"


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

    result = await db.execute(
        select(Node).where(Node.minion_id == payload.minion_id)
    )
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
        await db.commit()
        await db.refresh(node)
    else:
        node.bootstrap_status = "pending"
        node.bootstrap_ip = payload.target_ip
        node.bootstrap_logs = ""        # clear previous run's logs
        node.bootstrap_error = None     # clear previous error

    # Enforce: node must belong to at least one group before bootstrapping
    if not await node_has_group(node.id, db):
        raise HTTPException(
            status_code=400,
            detail="Node must belong to at least one group before bootstrapping. "
                   "Add the node to a group first, then configure group SSH credentials."
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
    await db.commit()
    await db.refresh(node)

    # If a stale accepted Salt key exists for this minion, delete it now.
    # Re-bootstrap generates a new keypair on the minion; the old master key
    # causes authentication to loop indefinitely ("cached the public key…").
    import os as _os
    _pki_base = _os.environ.get("SALT_PKI_DIR", "/etc/salt/pki/master")
    _accepted_key = __import__("pathlib").Path(_pki_base) / "minions" / payload.minion_id
    salt_key_deleted = False
    if _accepted_key.exists():
        try:
            _accepted_key.unlink()
            salt_key_deleted = True
        except OSError:
            pass  # PKI volume not mounted or not writable — non-fatal

    task = bootstrap_node.delay(
        str(node.id),
        payload.target_ip,
        ssh_username=payload.ssh_username,
        ssh_password=payload.ssh_password,
    )

    msg = "Bootstrap queued. Node will appear in fleet once Salt minion connects."
    if salt_key_deleted:
        msg = (
            "Bootstrap queued. The node's previous Salt key was removed — "
            "a new key will appear in Minion Keys for approval once the minion reconnects."
        )

    return BootstrapResponse(
        node_id=node.id,
        minion_id=node.minion_id,
        job_id=task.id,
        bootstrap_status="pending",
        message=msg,
        salt_key_deleted=salt_key_deleted,
    )


@router.get("/bootstrap/{node_id}/status")
async def bootstrap_status(
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
        "bootstrap_ip": node.bootstrap_ip,
        "bootstrap_error": node.bootstrap_error,
    }


@router.post("/bootstrap/{node_id}/cancel")
async def cancel_bootstrap(
    node_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("operator", "admin")),
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

    # Read the Salt pillar file written before the Ansible run
    pillar_content: str | None = None
    pillar_path = Path("/srv/salt/pillar") / f"{node.minion_id}.sls"
    if pillar_path.exists():
        try:
            pillar_content = pillar_path.read_text()
        except Exception:
            pillar_content = f"(could not read {pillar_path})"
    else:
        pillar_content = f"(pillar file not found at {pillar_path})"

    return {
        "node_id": str(node.id),
        "minion_id": node.minion_id,
        "bootstrap_status": node.bootstrap_status,
        "pillar_path": str(pillar_path),
        "pillar": pillar_content,
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
    from fleet_platform.models.bootstrap_run import BootstrapRun
    from sqlalchemy import desc

    result = await db.execute(
        select(BootstrapRun)
        .where(BootstrapRun.node_id == node_id)
        .order_by(desc(BootstrapRun.started_at))
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    runs = result.scalars().all()

    total = await db.scalar(
        select(func.count()).select_from(
            select(BootstrapRun).where(BootstrapRun.node_id == node_id).subquery()
        )
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
    _: dict = Depends(require_role("viewer", "operator", "admin")),
):
    result = await db.execute(
        select(PlatformSetting).where(PlatformSetting.key == "playbook_sources")
    )
    setting = result.scalar_one_or_none()
    sources_json = setting.value if setting else None

    all_dirs = get_all_playbook_dirs(sources_json, _PLAYBOOKS_DIR)
    all_entries = []
    for d in all_dirs:
        all_entries.extend(discover_all(d))
    return [
        PlaybookEntryResponse(
            filename=e.filename,
            name=e.name,
            description=e.description,
            entry_type=e.entry_type,
            default_vars=e.default_vars,
        )
        for e in all_entries
    ]


@router.get("/sources", response_model=list[PlaybookSourceResponse])
async def list_sources(
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("viewer", "operator", "admin")),
):
    """List configured extra playbook sources."""
    import json as _json
    result = await db.execute(
        select(PlatformSetting).where(PlatformSetting.key == "playbook_sources")
    )
    setting = result.scalar_one_or_none()
    if not setting or not setting.value:
        return []
    try:
        sources = _json.loads(setting.value)
    except (ValueError, TypeError):
        return []
    return [
        PlaybookSourceResponse(index=i, **{k: v for k, v in src.items()})
        for i, src in enumerate(sources)
    ]


@router.post("/sources/validate", response_model=PlaybookSourceValidateResponse)
async def validate_source(
    payload: PlaybookSourceValidateRequest,
    _: dict = Depends(require_role("operator", "admin")),
):
    """Validate a playbook source without saving it. Returns scan results."""
    import asyncio
    import os
    import tempfile

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

        raw_url = payload.url.strip()
        branch = payload.branch or "main"

        # Build authenticated URL if token provided
        url = raw_url
        if payload.token:
            # Strip existing scheme and prepend token
            import re as _re
            scheme_match = _re.match(r'^(https?://)(.+)$', raw_url)
            if scheme_match:
                url = f"{scheme_match.group(1)}{payload.token}@{scheme_match.group(2)}"
            else:
                url = raw_url  # SSH or unknown scheme — leave as-is

        # Build SSH env if ssh_key provided
        ssh_env: dict | None = None
        _ssh_key_file = None
        if payload.ssh_key:
            _ssh_key_file = tempfile.NamedTemporaryFile(mode='w', suffix='.pem', delete=False, prefix='kri-ssh-')
            _ssh_key_file.write(payload.ssh_key)
            _ssh_key_file.flush()
            os.chmod(_ssh_key_file.name, 0o600)
            _ssh_key_file.close()
            ssh_env = {
                **os.environ,
                "GIT_SSH_COMMAND": f"ssh -i {_ssh_key_file.name} -o StrictHostKeyChecking=no",
            }

        try:
            # Step 1: ls-remote — fast, non-destructive connectivity check
            logs.append("[1/3] Testing connectivity to repository...")
            if payload.token:
                logs.append("[1/3] Authenticating with personal access token...")
            elif payload.ssh_key:
                logs.append("[1/3] Authenticating with SSH key...")

            try:
                ls_result = await asyncio.to_thread(
                    lambda: subprocess.run(
                        ["git", "ls-remote", "--exit-code", "--heads", url, f"refs/heads/{branch}"],
                        capture_output=True,
                        timeout=20,
                        env=ssh_env,
                    )
                )
                if ls_result.returncode != 0:
                    # Branch might exist but ls-remote filtering missed it — try without filter
                    ls_result2 = await asyncio.to_thread(
                        lambda: subprocess.run(
                            ["git", "ls-remote", "--exit-code", url],
                            capture_output=True,
                            timeout=20,
                            env=ssh_env,
                        )
                    )
                    if ls_result2.returncode != 0:
                        err = ls_result2.stderr.decode(errors="replace").strip()
                        logs.append(f"[1/3] ✗ Cannot access repository: {err or 'connection refused or repo not found'}")
                        return PlaybookSourceValidateResponse(
                            valid=False,
                            error=f"Cannot access git repository: {err or 'connection refused or repo not found'}",
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
            with tempfile.TemporaryDirectory(prefix="kri-validate-") as tmpdir:
                clone_cmd = ["git", "clone", "--depth=1", "--single-branch"]
                if branch != "HEAD":
                    clone_cmd += ["--branch", branch]
                clone_cmd += [url, tmpdir]

                try:
                    clone_result = await asyncio.to_thread(
                        lambda: subprocess.run(clone_cmd, capture_output=True, timeout=60, env=ssh_env)
                    )
                    if clone_result.returncode != 0:
                        err = clone_result.stderr.decode(errors="replace").strip()
                        logs.append(f"[2/3] ✗ Clone failed: {err[:200]}")
                        return PlaybookSourceValidateResponse(
                            valid=False,
                            error=f"Clone failed: {err[:300]}",
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
        finally:
            # Clean up temp SSH key file if created
            if _ssh_key_file is not None:
                try:
                    os.unlink(_ssh_key_file.name)
                except OSError:
                    pass

    return PlaybookSourceValidateResponse(valid=False, error=f"Unknown source type: {payload.type}", logs=logs)


@router.post("/sources", response_model=PlaybookSourceResponse, status_code=201)
async def add_source(
    payload: PlaybookSourceRequest,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("operator", "admin")),
):
    """Add a new playbook source (local directory or git repository)."""
    import asyncio
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
        url = payload.url.strip()
        ls = await asyncio.to_thread(
            lambda: subprocess.run(
                ["git", "ls-remote", "--exit-code", url],
                capture_output=True, timeout=20,
            )
        )
        if ls.returncode != 0:
            err = ls.stderr.decode(errors="replace").strip()
            raise HTTPException(status_code=422, detail=f"Cannot access git repository: {err[:200] or 'connection refused'}")

    result = await db.execute(
        select(PlatformSetting).where(PlatformSetting.key == "playbook_sources")
    )
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
    await db.commit()

    return PlaybookSourceResponse(index=new_index, **new_src)


@router.delete("/sources/{index}", status_code=204)
async def remove_source(
    index: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("operator", "admin")),
):
    """Remove a playbook source by its index."""
    import json as _json
    result = await db.execute(
        select(PlatformSetting).where(PlatformSetting.key == "playbook_sources")
    )
    setting = result.scalar_one_or_none()
    if not setting or not setting.value:
        raise HTTPException(status_code=404, detail="No sources configured")
    try:
        sources = _json.loads(setting.value)
    except (ValueError, TypeError):
        raise HTTPException(status_code=500, detail="Corrupt sources setting")
    if index < 0 or index >= len(sources):
        raise HTTPException(status_code=404, detail=f"Source index {index} not found")
    sources.pop(index)
    setting.value = _json.dumps(sources)
    await db.commit()


@router.post("/sources/sync", response_model=PlaybookSourceSyncResult)
async def sync_sources(
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("operator", "admin")),
):
    """Force-sync all configured git playbook sources."""
    result = await db.execute(
        select(PlatformSetting).where(PlatformSetting.key == "playbook_sources")
    )
    setting = result.scalar_one_or_none()
    sources_json = setting.value if setting else None
    sync_results = sync_all_git_sources(sources_json)
    return PlaybookSourceSyncResult(results=sync_results)


@router.post("/sources/import", response_model=dict)
async def import_sources_csv(
    payload: PlaybookSourcesImportRequest,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("operator", "admin")),
):
    """Bulk-import playbook sources from CSV text.

    Format (one entry per line):
        type, path/url, branch (for git; leave blank for local), label
    Lines starting with '#' are treated as comments and ignored.
    """
    import json as _json
    result = await db.execute(
        select(PlatformSetting).where(PlatformSetting.key == "playbook_sources")
    )
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
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("operator", "admin")),
):
    """Return the dependency tree of a playbook/role in execution order."""
    import yaml as _yaml

    from fleet_platform.services.platform_settings_svc import get_playbooks_dir
    playbooks_dir = await get_playbooks_dir(db)

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
            for key in ("include_tasks", "import_tasks", "ansible.builtin.include_tasks", "ansible.builtin.import_tasks"):
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

        for play in (plays if isinstance(plays, list) else []):
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
        raise HTTPException(status_code=404, detail=f"Playbook not found")
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
        extravars=payload.extravars,
        status="pending",
        triggered_by=claims["sub"],
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    run_playbook.delay(
        str(job.id),
        ssh_username=payload.ssh_username,
        ssh_password=payload.ssh_password,
    )

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


@router.get("/jobs/{job_id}", response_model=AnsibleJobResponse)
async def get_ansible_job(
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("viewer", "operator", "admin")),
):
    result = await db.execute(select(AnsibleJob).where(AnsibleJob.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return AnsibleJobResponse(
        id=job.id,
        playbook=job.playbook,
        target_type=job.target_type,
        target_label=job.target_label,
        extravars=job.extravars,
        status=job.status,
        triggered_by=job.triggered_by,
        started_at=job.started_at,
        completed_at=job.completed_at,
        stdout=job.stdout,
        rc=job.rc,
        created_at=job.created_at,
    )


@router.get("/files")
async def list_playbook_files(
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("operator", "admin")),
):
    """Return the full recursive file tree of the playbooks directory."""
    from fleet_platform.services.platform_settings_svc import get_playbooks_dir
    playbooks_dir = await get_playbooks_dir(db)

    def _walk(path: Path, rel: str = "") -> list[dict]:
        items = []
        try:
            entries = sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name))
        except PermissionError:
            return items
        for entry in entries:
            entry_rel = f"{rel}/{entry.name}".lstrip("/")
            if entry.name.startswith(".") or entry.name == "__pycache__":
                continue
            if entry.is_dir():
                items.append({
                    "name": entry.name,
                    "path": entry_rel,
                    "type": "dir",
                    "children": _walk(entry, entry_rel),
                })
            else:
                items.append({
                    "name": entry.name,
                    "path": entry_rel,
                    "type": "file",
                    "size": entry.stat().st_size,
                    "ext": entry.suffix.lstrip("."),
                })
        return items

    return {"root": str(playbooks_dir), "tree": _walk(playbooks_dir)}


@router.get("/files/content")
async def get_playbook_file(
    path: str = Query(..., description="Relative path within playbooks dir"),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("operator", "admin")),
):
    """Return the content of a file in the playbooks directory."""
    from fleet_platform.services.platform_settings_svc import get_playbooks_dir
    playbooks_dir = await get_playbooks_dir(db)
    target = (playbooks_dir / path).resolve()
    # Security: must remain inside playbooks_dir
    if not str(target).startswith(str(playbooks_dir.resolve())):
        raise HTTPException(status_code=400, detail="Path traversal not allowed")
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    try:
        content = target.read_text(errors="replace")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"path": path, "content": content, "size": target.stat().st_size}


@router.put("/files/content")
async def update_playbook_file(
    path: str = Query(..., description="Relative path within playbooks dir"),
    payload: dict = Body(...),
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_role("admin")),
):
    """Write content to a file in the playbooks directory. Admin only."""
    from fleet_platform.services.platform_settings_svc import get_playbooks_dir
    playbooks_dir = await get_playbooks_dir(db)
    target = (playbooks_dir / path).resolve()
    if not str(target).startswith(str(playbooks_dir.resolve())):
        raise HTTPException(status_code=400, detail="Path traversal not allowed")
    content = payload.get("content", "")
    if not isinstance(content, str):
        raise HTTPException(status_code=422, detail="content must be a string")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    return {"path": path, "size": target.stat().st_size, "saved": True}


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
