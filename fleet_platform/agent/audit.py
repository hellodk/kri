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
    """Redact sensitive fields from tool-call args before audit logging (#781).

    Delegates to :func:`fleet_platform.services.prompt_safety.redact_args` which
    applies a key-name blocklist (password, secret, token, etc.) and a length cap.
    """
    from fleet_platform.services.prompt_safety import redact_args

    return redact_args(args)


def _is_sensitive_key(key: str) -> bool:
    from fleet_platform.services.prompt_safety import is_sensitive_key

    return is_sensitive_key(key)


# Keep sensitive key constants visible at module level for external consumers.
_SENSITIVE_KEY_PATTERNS = None  # authoritative set lives in prompt_safety._SENSITIVE_KEYS
