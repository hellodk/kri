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
from fleet_platform.agent.loop import AgentLoop
from fleet_platform.agent.planner import LLMPlanner
from fleet_platform.agent.registry import ToolCtx
from fleet_platform.agent.tools import build_default_registry
from fleet_platform.api.deps import get_db
from fleet_platform.api.limiter import limiter
from fleet_platform.core.auth import require_role
from fleet_platform.models.agent_session import AgentSession
from fleet_platform.models.llm_query_log import LLMQueryLog
from fleet_platform.services import llm_svc

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
    if payload.endpoint_id:
        endpoint = await llm_svc.get_endpoint(db, payload.endpoint_id)
        if not endpoint:
            raise HTTPException(status_code=404, detail="LLM endpoint not found")
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
    executor = Executor(registry, audit_hook=audit_tool_dispatch)
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

        yield _sse({"type": "session_start", "session_id": str(session.id), "model": chosen_model})

        try:
            async for event in loop.run(payload.prompt):
                if event.type == "step_start":
                    iterations = max(iterations, int(event.data.get("iteration", iterations)))
                elif event.type == "tool_call":
                    tool_calls.append({"name": event.data.get("name"), "args": event.data.get("args")})
                elif event.type == "final":
                    final_text = event.data.get("text")
                elif event.type in ("limit_reached", "aborted"):
                    terminal = "aborted"
                yield _sse({"type": event.type, **event.data})
        except Exception as exc:  # noqa: BLE001 — always emit a terminal frame
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
