"""Audit hook for the executor (#711 / #714).

Every tool dispatch is written to the audit log with ``actor`` set to the
**operator email** carried on the ToolCtx — never "agent". This is the
confused-deputy guarantee: the audit trail always answers "which human is
accountable for this call?" even though an LLM chose to make it.
"""

from __future__ import annotations

import structlog

from fleet_platform.agent.executor import ToolResult
from fleet_platform.agent.registry import ToolCtx, ToolSpec

logger = structlog.get_logger(__name__)


async def audit_tool_dispatch(ctx: ToolCtx, spec: ToolSpec, args: dict, result: ToolResult) -> None:
    """Persist one audit row per dispatch. Best-effort: never breaks the run."""
    from fleet_platform.core.audit import audit

    if ctx.db is None:
        return
    try:
        await audit(
            ctx.db,
            actor=ctx.actor,
            action=f"agent.tool.{spec.name}",
            resource_type="agent_tool",
            new_value={
                "session_id": str(ctx.session_id) if ctx.session_id else None,
                "tool": spec.name,
                "side_effect": spec.side_effect,
                "args": _redact(args),
                "ok": result.ok,
                "status": result.status,
                "cached": result.cached,
                "error": result.error,
            },
        )
        await ctx.db.commit()
    except Exception:  # noqa: BLE001 — auditing must not abort the agent turn
        logger.warning("agent_audit_failed", tool=spec.name, exc_info=True)
        try:
            await ctx.db.rollback()
        except Exception:  # noqa: BLE001
            pass


def _redact(args: dict) -> dict:
    """Drop obviously large/sensitive fields from the audit payload."""
    out: dict = {}
    for k, v in (args or {}).items():
        if isinstance(v, str) and len(v) > 500:
            out[k] = v[:500] + "...[truncated]"
        else:
            out[k] = v
    return out
