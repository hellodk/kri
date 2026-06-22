"""Safety guards for agent live-apply tools (#714).

These run *before* a gated live action is proposed for approval. They are
defense-in-depth on top of approval + co-sign: even an approved action is
refused if it targets the control plane or would let a planner session take its
own planner minis offline (self-deplane). PROTECTED_TARGETS is reused from the
PendingAction model so the agent and the manual node-action path share one list.
"""

from __future__ import annotations

import os

from fleet_platform.models.pending_action import PendingAction

# Minions serving the planner tier are off-limits to agent-initiated node/service
# control — a planner must not be able to deplane the brain it is running on.
PROTECTED_NODES: frozenset[str] = frozenset(
    n.strip().lower() for n in os.getenv("AGENT_PROTECTED_NODES", "mm1,mm2").split(",") if n.strip()
)

# Tools whose effect can take a host/service out of service.
_DEPLANING_TOOLS = {"restart_service", "set_pillar", "apply_salt_state", "enable_node", "disable_node"}


class GuardError(PermissionError):
    """Raised when a live action is refused by a safety guard."""


def _arg(args: dict, *keys: str) -> str | None:
    for k in keys:
        v = args.get(k)
        if v:
            return str(v)
    return None


def assert_live_action_allowed(tool_name: str, args: dict) -> None:
    """Refuse live actions against protected targets / protected nodes.

    Raises GuardError with an operator-readable reason; the caller surfaces it
    as a tool error (the action is never proposed for approval).
    """
    target_name = _arg(args, "name", "service", "process_name", "pillar_key")
    if target_name and PendingAction.is_protected_target(target_name):
        raise GuardError(f"{target_name!r} is a protected control-plane target and cannot be modified by the agent")

    node = _arg(args, "minion_id", "node", "target", "minion")
    if node and tool_name in _DEPLANING_TOOLS and node.strip().lower() in PROTECTED_NODES:
        raise GuardError(f"node {node!r} serves the planner tier; a planner session may not deplane its own minis")


def co_sign_required(target_count: int | None) -> bool:
    """True when an action hits more than the co-sign threshold of targets (#714)."""
    return bool(target_count is not None and target_count > PendingAction.CO_SIGN_THRESHOLD)
