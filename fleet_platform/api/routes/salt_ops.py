# fleet_platform/api/routes/salt_ops.py
"""Salt state runner API — browse states, apply them, run ad-hoc commands."""

import os
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
    from fleet_platform.workers.salt_tasks import apply_salt_state

    task = apply_salt_state.delay(
        state_name=payload.state,
        target_minions=payload.minion_ids,
        pillar_data=payload.pillar,
    )
    await audit(
        db,
        actor=claims["email"],
        action="salt.state.apply",
        resource_type="salt_state",
        new_value={"state": payload.state, "minion_ids": payload.minion_ids, "task_id": task.id},
    )
    await db.commit()
    return {"task_id": task.id}


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
    import json as _json

    from fleet_platform.services.platform_settings_svc import (
        _DEFAULT_SALT_FUNCTIONS,
        _SALT_MINIMUM_FUNCTIONS,
        SALT_ALLOWED_FUNCTIONS,
        get_setting,
    )
    from fleet_platform.workers.salt_tasks import run_salt_cmd

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
    task = run_salt_cmd.delay(
        function=payload.function,
        target_minions=payload.minion_ids,
        args=payload.args,
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
