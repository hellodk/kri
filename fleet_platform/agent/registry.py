"""Typed tool registry for the agent (#711).

A `ToolSpec` is a frozen, self-describing capability: JSON-Schema params, the
minimum role required to call it, its side-effect tier, approval/dry-run flags
and an `enabled` kill-switch (#716 decision #9). The `ToolRegistry` is the
catalogue; crucially `available_for_role` filters by role **and** kill-switch so
the model is never even shown a tool it cannot call (the executor re-checks at
dispatch — belt and suspenders).

Schema exporters cover the three live tool-calling backends plus prompt-embedded
JSON mode, matching `LLMEndpoint.tool_mode` (native / anthropic / json).
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from fleet_platform.core.auth import role_satisfies

# Side-effect tiers, ordered least → most dangerous (mirrors the epic risk tiers).
SIDE_EFFECTS = ("read", "execute_read", "write_quarantine", "write_live", "promote")
_VALID_ROLES = ("viewer", "operator", "admin")

ToolHandler = Callable[..., Awaitable[Any]]


@dataclass(frozen=True)
class ToolSpec:
    """One agent capability. Frozen so a registered spec can't mutate under us."""

    name: str
    description: str
    params_schema: dict[str, Any]
    required_role: str = "operator"
    side_effect: str = "read"
    requires_approval: bool = False
    requires_dry_run_first: bool = False
    enabled: bool = True
    handler: ToolHandler | None = None

    def __post_init__(self) -> None:
        if not self.name or not self.name.replace("_", "").isalnum():
            raise ValueError(f"tool name must be alphanumeric/underscore: {self.name!r}")
        if self.side_effect not in SIDE_EFFECTS:
            raise ValueError(f"invalid side_effect {self.side_effect!r}; must be one of {SIDE_EFFECTS}")
        if self.required_role not in _VALID_ROLES:
            raise ValueError(f"invalid required_role {self.required_role!r}; must be one of {_VALID_ROLES}")
        if not isinstance(self.params_schema, dict) or self.params_schema.get("type") != "object":
            raise ValueError("params_schema must be a JSON-Schema object ({'type': 'object', ...})")

    def to_openai_tool(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.params_schema,
            },
        }

    def to_anthropic_tool(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.params_schema,
        }

    def to_prompt_section(self) -> str:
        props = (self.params_schema or {}).get("properties", {})
        required = set((self.params_schema or {}).get("required", []))
        if props:
            arg_lines = []
            for arg, spec in props.items():
                typ = spec.get("type", "any")
                flag = "required" if arg in required else "optional"
                desc = spec.get("description", "")
                arg_lines.append(f"    - {arg} ({typ}, {flag}){f': {desc}' if desc else ''}")
            args = "\n".join(arg_lines)
        else:
            args = "    (no arguments)"
        return f"- {self.name}: {self.description}\n{args}"


@dataclass
class ToolCtx:
    """Per-dispatch context. ``actor`` is the operator email — never 'agent' —
    so every audit row / span answers 'who fired this?' (#714)."""

    actor: str
    role: str
    session_id: uuid.UUID | None = None
    db: Any = None
    extra: dict[str, Any] = field(default_factory=dict)


class ToolRegistry:
    """In-memory catalogue of ToolSpecs keyed by name."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> ToolSpec:
        if spec.name in self._tools:
            raise ValueError(f"tool already registered: {spec.name!r}")
        self._tools[spec.name] = spec
        return spec

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def all(self) -> list[ToolSpec]:
        return list(self._tools.values())

    def available_for_role(self, role: str | None) -> list[ToolSpec]:
        """Enabled tools the role may call. Kill-switched tools are never returned."""
        return [t for t in self._tools.values() if t.enabled and role_satisfies(role, t.required_role)]

    def to_openai_tools(self, role: str | None) -> list[dict[str, Any]]:
        return [t.to_openai_tool() for t in self.available_for_role(role)]

    def to_anthropic_tools(self, role: str | None) -> list[dict[str, Any]]:
        return [t.to_anthropic_tool() for t in self.available_for_role(role)]

    def to_prompt_section(self, role: str | None) -> str:
        tools = self.available_for_role(role)
        if not tools:
            return "No tools are available to you."
        body = "\n".join(t.to_prompt_section() for t in tools)
        return "## Available Tools\n" + body
