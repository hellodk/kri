"""Agent subsystem: typed tool registry, executor and bounded loop (#711).

Phase B of the agentic transformation epic (#716). The registry is the single
catalogue of what the agent can do; the executor enforces RBAC, validation,
idempotency and audit on every dispatch; the loop drives planner ↔ tools.
"""

from fleet_platform.agent.executor import (
    Executor,
    IdempotencyCache,
    ToolResult,
    validate_args,
)
from fleet_platform.agent.registry import (
    SIDE_EFFECTS,
    ToolCtx,
    ToolRegistry,
    ToolSpec,
)

__all__ = [
    "SIDE_EFFECTS",
    "ToolCtx",
    "ToolRegistry",
    "ToolSpec",
    "Executor",
    "IdempotencyCache",
    "ToolResult",
    "validate_args",
]
