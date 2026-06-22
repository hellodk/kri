"""Agent run endpoint (#711).

``POST /api/v1/agent/run/stream`` drives a bounded, tool-using agent turn and
streams every step as Server-Sent Events. The flow:

1. resolve the LLM endpoint (explicit or default),
2. open an :class:`AgentSession` (owned by the operator — never "agent"),
3. build the read-only tool registry, executor (with the audit hook), the
   LLM planner, and the bounded loop,
4. stream ``step_start`` / ``tool_call`` / ``tool_result`` / ``awaiting_approval``
   / ``final`` / ``limit_reached`` events,
5. finalize the session and persist an ``llm_query_log`` row linked to it.

Every tool dispatch is audited inside the executor with ``actor`` = operator
email, so the agent can never act as a confused deputy.
"""

from __future__ import annotations

import json
import logging
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.agent.audit import audit_tool_dispatch
from fleet_platform.agent.executor import Executor
from fleet_platform.agent.guards import assert_live_action_allowed
from fleet_platform.agent.loop import AgentLoop
from fleet_platform.agent.planner import LLMPlanner
from fleet_platform.agent.registry import ToolCtx
from fleet_platform.agent.tools import build_default_registry
from fleet_platform.api.deps import get_db
from fleet_platform.api.limiter import limiter
from fleet_platform.core.auth import require_role
from fleet_platform.models.agent_session import AgentSession
from fleet_platform.models.llm_query_log import LLMQueryLog
from fleet_platform.services import agent_apply_svc, llm_svc, tier_router

router = APIRouter(prefix="/api/v1/agent", tags=["agent"])

logger = logging.getLogger(__name__)


class AgentRunRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=4000)
    endpoint_id: uuid.UUID | None = None


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, default=str)}\n\n"


@router.post("/run/stream")
@limiter.limit("10/minute")
async def run_agent_stream(
    request: Request,
    payload: AgentRunRequest,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_role("operator", "admin")),
):
    routed_via: str | None = None
    if payload.endpoint_id:
        endpoint = await llm_svc.get_endpoint(db, payload.endpoint_id)
        if not endpoint:
            raise HTTPException(status_code=404, detail="LLM endpoint not found")
    else:
        # Dogfood the tier router: pick a local planner-tier endpoint, allowing the
        # admin-gated cloud fallback only for admins (#712 / #716 d8). Fall back to
        # the configured default if no tier-tagged endpoint exists yet.
        route = await tier_router.select_endpoint(db, "planner", allow_cloud=claims["role"] == "admin")
        if route is not None:
            endpoint = route.endpoint
            routed_via = route.matched_tag + ("/cloud" if route.via_cloud else "")
        else:
            endpoint = await llm_svc.get_default_endpoint(db)
        if not endpoint:
            raise HTTPException(
                status_code=422,
                detail="No default LLM endpoint configured. Add one in Settings -> LLM.",
            )
    if not endpoint.enabled:
        raise HTTPException(status_code=422, detail="Selected LLM endpoint is disabled")

    from fleet_platform.api.routes.llm import _resolve_model

    api_key = llm_svc.get_decrypted_api_key(endpoint)
    chosen_model = await _resolve_model(endpoint)
    model_caps = (
        [c.strip() for c in endpoint.model_capabilities.split(",") if c.strip()] if endpoint.model_capabilities else []
    )

    # Open the session up front so even an aborted/disconnected run is recorded.
    session = AgentSession(
        user_id=claims["sub"],
        endpoint_id=endpoint.id,
        status="active",
        initial_prompt=payload.prompt,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)

    registry = build_default_registry()
    executor = Executor(registry, audit_hook=audit_tool_dispatch, guard_hook=assert_live_action_allowed)
    planner = LLMPlanner(
        registry=registry,
        role=claims["role"],
        base_url=endpoint.base_url,
        model=chosen_model,
        max_tokens=endpoint.max_tokens,
        api_key=api_key,
        provider=endpoint.provider,
        model_context_length=endpoint.model_context_length,
        model_capabilities=model_caps,
    )
    ctx = ToolCtx(actor=claims["email"], role=claims["role"], session_id=session.id, db=db)
    loop = AgentLoop(executor, planner, ctx)

    async def event_stream():
        t0 = time.perf_counter()
        iterations = 0
        tool_calls: list[dict] = []
        final_text: str | None = None
        terminal = "completed"
        error: str | None = None

        yield _sse(
            {
                "type": "session_start",
                "session_id": str(session.id),
                "model": chosen_model,
                "routed_via": routed_via,
            }
        )

        try:
            with tier_router.lease(endpoint):
                async for event in loop.run(payload.prompt):
                    if event.type == "step_start":
                        iterations = max(iterations, int(event.data.get("iteration", iterations)))
                    elif event.type == "tool_call":
                        tool_calls.append({"name": event.data.get("name"), "args": event.data.get("args")})
                    elif event.type == "final":
                        final_text = event.data.get("text")
                    elif event.type in ("limit_reached", "aborted"):
                        terminal = "aborted"
                    elif event.type == "awaiting_approval":
                        # Turn the proposed live action into a PendingAction for
                        # human approval (+ co-sign when it hits > N targets).
                        terminal = "awaiting_approval"
                        try:
                            action = await agent_apply_svc.create_proposal(
                                db,
                                session_id=session.id,
                                actor=claims["email"],
                                tool_name=event.data.get("name"),
                                args=event.data.get("args") or {},
                                dry_run_result=event.data.get("dry_run_result"),
                            )
                            event.data["pending_action_id"] = str(action.id)
                            event.data["co_sign_required"] = action.co_sign_required
                            event.data["target_count"] = action.target_count
                        except Exception as exc:  # noqa: BLE001 — guard refusal or db error
                            event.data["proposal_error"] = str(exc)
                    yield _sse({"type": event.type, **event.data})
        except Exception as exc:  # noqa: BLE001 — always emit a terminal frame
            # A planner call failure trips the endpoint's health cooldown so the
            # router steers subsequent sessions elsewhere.
            tier_router.STATE.mark_unhealthy(str(endpoint.id))
            error = f"agent run failed: {exc}"
            terminal = "aborted"
            logger.exception("run_agent_stream failed", extra={"session_id": str(session.id)})
            yield _sse({"type": "error", "error": error})

        duration_ms = int((time.perf_counter() - t0) * 1000)

        # Finalize the session + persist a linked query log (best-effort).
        try:
            session.status = terminal
            session.iteration_count = iterations
            session.tool_call_count = len(tool_calls)
            session.error = error
            db.add(session)

            log = LLMQueryLog(
                endpoint_id=endpoint.id,
                user_id=claims["sub"],
                intent="agent",
                prompt=payload.prompt,
                system_prompt=planner._system_prompt()[:500],
                response=final_text,
                model_used=chosen_model,
                input_tokens=planner.input_tokens,
                output_tokens=planner.output_tokens,
                duration_ms=duration_ms,
                error=error,
                tool_calls=tool_calls or None,
                agent_session_id=session.id,
            )
            db.add(log)
            await db.commit()
            query_id = str(log.id)
        except Exception:  # noqa: BLE001
            logger.exception("run_agent_stream: persist failed")
            await db.rollback()
            query_id = None

        yield _sse(
            {
                "type": "done",
                "session_id": str(session.id),
                "query_id": query_id,
                "status": terminal,
                "iterations": iterations,
                "tool_calls": len(tool_calls),
                "input_tokens": planner.input_tokens,
                "output_tokens": planner.output_tokens,
                "duration_ms": duration_ms,
            }
        )
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )


@router.get("/artifacts")
async def list_artifacts(
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_role("operator", "admin")),
):
    """List the caller's quarantined artifacts (across sessions, newest first)."""
    from fleet_platform.services import agent_quarantine as q

    try:
        return {"artifacts": q.list_artifacts(claims["email"])}
    except q.QuarantineError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/artifacts/{session_id}/{filename}")
async def get_artifact(
    session_id: str,
    filename: str,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_role("operator", "admin")),
):
    """Fetch one quarantined artifact's content + metadata."""
    from fleet_platform.services import agent_quarantine as q

    try:
        content, meta = q.read_artifact(claims["email"], session_id, filename)
    except q.QuarantineError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"content": content, "metadata": meta}


@router.get("/artifacts/{session_id}/{filename}/diff")
async def diff_artifact(
    session_id: str,
    filename: str,
    target: str | None = None,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_role("operator", "admin")),
):
    """Unified diff of a quarantined artifact vs the live tree.

    ``target`` is a path relative to the playbooks dir; when omitted (or not
    found), the diff is reported as a new file.
    """
    from pathlib import Path

    from fleet_platform.services import agent_quarantine as q
    from fleet_platform.services.artifact_diff import diff_text
    from fleet_platform.services.platform_settings_svc import get_playbooks_dir
    from fleet_platform.services.playbook_sources import get_all_playbook_dirs

    try:
        new_content, _meta = q.read_artifact(claims["email"], session_id, filename)
    except q.QuarantineError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    live_content: str | None = None
    if target:
        playbooks_dir = await get_playbooks_dir(db)
        roots = [d.resolve() for d in get_all_playbook_dirs(None, playbooks_dir)]
        candidate = (Path(playbooks_dir) / target).resolve()
        if any(candidate.is_relative_to(r) for r in roots) and candidate.is_file():
            live_content = candidate.read_text(errors="replace")

    result = diff_text(live_content, new_content, fromfile=target or "live", tofile=filename)
    return {**result.as_dict(), "original": live_content or "", "modified": new_content}


@router.get("/tiers")
async def get_agent_tiers(
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_role("operator", "admin")),
):
    """Capability-tier snapshot: which endpoints serve planner/coder/worker/embed,
    their health and current in-flight load. Drives the local-cluster dashboard."""
    return await tier_router.tier_status(db)


@router.get("/actions")
async def list_agent_actions(
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_role("operator", "admin")),
):
    """List agent-proposed pending actions awaiting approval/co-sign."""
    from sqlalchemy import select

    from fleet_platform.models.pending_action import PendingAction

    rows = (
        (
            await db.execute(
                select(PendingAction)
                .where(PendingAction.proposed_by_agent.is_(True))
                .order_by(PendingAction.created_at.desc())
                .limit(50)
            )
        )
        .scalars()
        .all()
    )
    return {
        "actions": [
            {
                "id": str(a.id),
                "tool_name": a.tool_name,
                "params": json.loads(a.params or "{}"),
                "requested_by": a.requested_by,
                "status": a.status,
                "target_count": a.target_count,
                "co_sign_required": a.co_sign_required,
                "approved_by": a.approved_by,
                "co_signed_by": a.co_signed_by,
                "dry_run_result": json.loads(a.dry_run_result) if a.dry_run_result else None,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in rows
        ]
    }


async def _get_agent_action(db: AsyncSession, action_id: str):
    from sqlalchemy import select

    from fleet_platform.models.pending_action import PendingAction

    try:
        aid = uuid.UUID(action_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid action id") from exc
    action = (await db.execute(select(PendingAction).where(PendingAction.id == aid))).scalar_one_or_none()
    if action is None or not action.proposed_by_agent:
        raise HTTPException(status_code=404, detail="agent action not found")
    return action


@router.post("/actions/{action_id}/approve")
@limiter.limit("20/minute")
async def approve_agent_action(
    request: Request,
    action_id: str,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_role("operator", "admin")),
):
    """Approve (and, when fully signed, execute) an agent-proposed live action.

    Execution runs as the original operator, not the approver."""
    action = await _get_agent_action(db, action_id)
    try:
        return await agent_apply_svc.approve_proposal(
            db, action, approver_email=claims["email"], approver_role=claims["role"]
        )
    except agent_apply_svc.ApprovalError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/actions/{action_id}/reject")
@limiter.limit("20/minute")
async def reject_agent_action(
    request: Request,
    action_id: str,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_role("operator", "admin")),
):
    action = await _get_agent_action(db, action_id)
    try:
        return await agent_apply_svc.reject_proposal(db, action, approver_email=claims["email"])
    except agent_apply_svc.ApprovalError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/artifacts/{session_id}/{filename}/promote")
@limiter.limit("10/minute")
async def promote_artifact(
    request: Request,
    session_id: str,
    filename: str,
    target: str,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_role("admin")),
):
    """Promote a quarantined artifact into the live playbook tree. **Admin only.**

    This is the single, deliberate path from quarantine to live — never a
    registry tool — and is always attributed to the promoting admin.
    """
    from pathlib import Path

    from fleet_platform.core.audit import audit
    from fleet_platform.services import agent_quarantine as q
    from fleet_platform.services.platform_settings_svc import get_playbooks_dir
    from fleet_platform.services.playbook_sources import get_all_playbook_dirs

    try:
        content, meta = q.read_artifact(claims["email"], session_id, filename)
    except q.QuarantineError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    playbooks_dir = await get_playbooks_dir(db)
    roots = [d.resolve() for d in get_all_playbook_dirs(None, playbooks_dir)]
    dest = (Path(playbooks_dir) / target).resolve()
    # Promotion target must stay inside an allowed playbook root.
    if not any(dest.is_relative_to(r) for r in roots):
        raise HTTPException(status_code=400, detail="promotion target is outside the playbook tree")
    if dest.is_symlink():
        raise HTTPException(status_code=400, detail="promotion target is a symlink")

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(content)

    await audit(
        db,
        actor=claims["email"],
        action="agent.artifact.promote",
        resource_type="playbook",
        new_value={
            "from": f"{session_id}:{filename}",
            "to": str(dest),
            "kind": (meta.get("metadata") or {}).get("kind"),
        },
    )
    await db.commit()
    return {"promoted": True, "target": str(dest)}


@router.get("/sessions")
async def list_agent_sessions(
    limit: int = 25,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_role("operator", "admin")),
):
    """List the caller's recent agent sessions (newest first)."""
    from sqlalchemy import select

    limit = max(1, min(int(limit), 100))
    rows = (
        (
            await db.execute(
                select(AgentSession)
                .where(AgentSession.user_id == claims["sub"])
                .order_by(AgentSession.created_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return {
        "sessions": [
            {
                "id": str(s.id),
                "status": s.status,
                "initial_prompt": s.initial_prompt,
                "iteration_count": s.iteration_count,
                "tool_call_count": s.tool_call_count,
                "error": s.error,
                "created_at": s.created_at.isoformat() if s.created_at else None,
            }
            for s in rows
        ]
    }
