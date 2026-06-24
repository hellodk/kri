# fleet_platform/api/routes/salt_ops.py
"""Salt state runner API — browse states, apply them, run ad-hoc commands."""

import os
import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.api.deps import get_db
from fleet_platform.core.audit import audit
from fleet_platform.core.auth import get_current_user, require_role

router = APIRouter(prefix="/api/v1/salt")

# The salt/states directory is mounted at /srv/salt/states inside the container.
_STATES_DIR = Path(os.environ.get("SALT_STATES_DIR", "/srv/salt/states"))

# Allowlist regex for Salt state names: dotted identifiers only (e.g. "jenkins_slave.init").
# Rejects shell metacharacters, path traversal, glob wildcards, and commas.
_STATE_NAME_RE = re.compile(r"^[a-zA-Z0-9_][a-zA-Z0-9_.-]*$")

# Allowlist regex for minion IDs — mirrors salt_keys.py _MINION_ID_RE.
# Rejects * / globs / commas / shell metacharacters.
_MINION_ID_RE = re.compile(r"^[a-zA-Z0-9._-]+$")


def _validate_state_name(state: str) -> None:
    if not _STATE_NAME_RE.match(state):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid state name {state!r}. Only dotted identifiers are allowed (e.g. 'jenkins_slave.init').",
        )


def _validate_minion_ids(minion_ids: list[str]) -> None:
    for mid in minion_ids:
        if not _MINION_ID_RE.match(mid):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid minion_id {mid!r}. Globs, wildcards, and shell characters are not allowed.",
            )


def _scan_states(base: Path) -> list[dict]:
    """Recursively scan the states dir and return a flat list of state descriptors."""
    states: list[dict] = []
    if not base.exists():
        return states
    for sls in sorted(base.rglob("*.sls")):
        rel = sls.relative_to(base)
        # Convert path to Salt dotted notation: jenkins_slave/init.sls → jenkins_slave.init
        parts = list(rel.parts)
        parts[-1] = parts[-1].removesuffix(".sls")
        dot_name = ".".join(parts)
        # Human display: drop trailing .init  (jenkins_slave.init → jenkins_slave)
        display = dot_name.removesuffix(".init")
        states.append(
            {
                "name": dot_name,
                "display": display,
                "path": str(rel),
            }
        )
    return states


class ApplyRequest(BaseModel):
    state: str
    minion_ids: list[str]
    pillar: dict | None = None
    # When true, dispatches `state.apply ... test=True`. Salt evaluates the
    # state tree and reports what *would* change without making changes —
    # the same dry-run behaviour as `salt-call --local state.apply test=True`
    # at the CLI. Used by the UI's "Dry-run" toggle to preview impact before
    # committing real changes.
    test: bool = False


class CmdRequest(BaseModel):
    function: str
    minion_ids: list[str]
    args: list[str] | None = None


@router.get("/states")
async def list_states(_: dict = Depends(get_current_user)):
    """Return the tree of available Salt states from the states directory."""
    states = _scan_states(_STATES_DIR)
    return {"states": states, "states_dir": str(_STATES_DIR)}


@router.post("/apply", status_code=202)
async def apply_state(
    payload: ApplyRequest,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_role("operator", "admin")),
):
    """Queue a Salt state.apply task. Returns the Celery task_id."""
    if not payload.minion_ids:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="minion_ids must not be empty",
        )
    _validate_state_name(payload.state)
    _validate_minion_ids(payload.minion_ids)
    from fleet_platform.workers.celery_app import celery_app

    task = celery_app.send_task(
        "fleet_platform.workers.salt_tasks.apply_salt_state",
        kwargs={
            "state_name": payload.state,
            "target_minions": payload.minion_ids,
            "pillar_data": payload.pillar,
            "test_mode": payload.test,
        },
        queue="maintenance",
    )
    await audit(
        db,
        actor=claims["email"],
        action="salt.state.apply.test" if payload.test else "salt.state.apply",
        resource_type="salt_state",
        new_value={
            "state": payload.state,
            "minion_ids": payload.minion_ids,
            "task_id": task.id,
            "test": payload.test,
        },
    )
    await db.commit()
    return {"task_id": task.id, "test": payload.test}


@router.get("/allowlist")
async def get_salt_allowlist(
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("operator", "admin")),
):
    """Return the current Salt function allowlist from platform settings."""
    from fleet_platform.services.platform_settings_svc import (
        _DEFAULT_SALT_FUNCTIONS,
        _SALT_MINIMUM_FUNCTIONS,
        SALT_ALLOWED_FUNCTIONS,
        get_setting,
    )

    raw = await get_setting(db, SALT_ALLOWED_FUNCTIONS)
    import json as _json

    if raw:
        try:
            funcs = sorted(set(_json.loads(raw)) | _SALT_MINIMUM_FUNCTIONS)
        except (ValueError, TypeError):
            funcs = sorted(_DEFAULT_SALT_FUNCTIONS)
    else:
        funcs = sorted(_DEFAULT_SALT_FUNCTIONS)
    return {
        "functions": funcs,
        "locked": sorted(_SALT_MINIMUM_FUNCTIONS),
    }


@router.post("/cmd", status_code=202)
async def run_cmd(
    payload: CmdRequest,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_role("operator", "admin")),
):
    """Queue an ad-hoc Salt command. Returns the Celery task_id."""
    if not payload.minion_ids:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="minion_ids must not be empty",
        )
    _validate_minion_ids(payload.minion_ids)
    import json as _json

    from fleet_platform.services.platform_settings_svc import (
        _DEFAULT_SALT_FUNCTIONS,
        _SALT_MINIMUM_FUNCTIONS,
        SALT_ALLOWED_FUNCTIONS,
        get_setting,
    )
    from fleet_platform.workers.celery_app import celery_app

    raw = await get_setting(db, SALT_ALLOWED_FUNCTIONS)
    if raw:
        try:
            allowed: frozenset[str] = frozenset(_json.loads(raw)) | _SALT_MINIMUM_FUNCTIONS
        except (ValueError, TypeError):
            allowed = _DEFAULT_SALT_FUNCTIONS | _SALT_MINIMUM_FUNCTIONS
    else:
        allowed = _DEFAULT_SALT_FUNCTIONS | _SALT_MINIMUM_FUNCTIONS

    if payload.function not in allowed:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(f"Function '{payload.function}' is not in the allowlist. Allowed functions: {sorted(allowed)}"),
        )
    task = celery_app.send_task(
        "fleet_platform.workers.salt_tasks.run_salt_cmd",
        kwargs={
            "function": payload.function,
            "target_minions": payload.minion_ids,
            "args": payload.args,
        },
        queue="maintenance",
    )
    await audit(
        db,
        actor=claims["email"],
        action="salt.cmd.run",
        resource_type="salt_cmd",
        new_value={"function": payload.function, "minion_ids": payload.minion_ids, "task_id": task.id},
    )
    await db.commit()
    return {"task_id": task.id}
