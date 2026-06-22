"""Tool executor — the single, audited choke-point for every tool call (#711).

`dispatch` enforces, in order:
  1. tool exists and is enabled (kill-switch),
  2. caller role re-check (belt-and-suspenders vs registry filtering),
  3. argument validation against the tool's JSON-Schema,
  4. approval gate — approval-gated tools never execute here (deferred to #714),
  5. dry-run-first gate,
  6. idempotency cache (per session),
  7. handler execution,
  8. audit with actor = operator email (confused-deputy guarantee, #714).

A dependency-free schema validator covers the subset our specs use (object,
required, additionalProperties, type, enum, min/maxLength, minimum/maximum).
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from fleet_platform.agent.registry import ToolCtx, ToolRegistry, ToolSpec
from fleet_platform.core.auth import role_satisfies

# Dispatch outcome statuses surfaced to the loop / SSE stream.
OK = "ok"
ERROR = "error"
DENIED = "denied"
AWAITING_APPROVAL = "awaiting_approval"
DRY_RUN_REQUIRED = "dry_run_required"

AuditHook = Callable[["ToolCtx", "ToolSpec", dict, "ToolResult"], Awaitable[None]]

_PY_TYPES: dict[str, tuple[type, ...]] = {
    "string": (str,),
    "integer": (int,),
    "number": (int, float),
    "boolean": (bool,),
    "array": (list,),
    "object": (dict,),
    "null": (type(None),),
}


@dataclass
class ToolResult:
    name: str
    ok: bool
    status: str = OK
    result: Any = None
    error: str | None = None
    cached: bool = False


def validate_args(schema: dict[str, Any], args: dict[str, Any]) -> str | None:
    """Return an error string if ``args`` violate ``schema``, else None."""
    if not isinstance(args, dict):
        return "arguments must be an object"
    props: dict[str, Any] = schema.get("properties", {})
    required = schema.get("required", [])

    for key in required:
        if key not in args:
            return f"missing required argument: {key}"

    if schema.get("additionalProperties", True) is False:
        extra = set(args) - set(props)
        if extra:
            return f"unexpected argument(s): {', '.join(sorted(extra))}"

    for key, value in args.items():
        spec = props.get(key)
        if not spec:
            continue
        err = _validate_value(key, value, spec)
        if err:
            return err
    return None


def _validate_value(key: str, value: Any, spec: dict[str, Any]) -> str | None:
    typ = spec.get("type")
    if typ:
        expected = _PY_TYPES.get(typ)
        # bool is a subclass of int — guard against it sneaking into integer/number
        if expected and (not isinstance(value, expected) or (typ in ("integer", "number") and isinstance(value, bool))):
            return f"argument {key!r} must be {typ}"
    if "enum" in spec and value not in spec["enum"]:
        return f"argument {key!r} must be one of {spec['enum']}"
    if isinstance(value, str):
        if "maxLength" in spec and len(value) > spec["maxLength"]:
            return f"argument {key!r} exceeds maxLength {spec['maxLength']}"
        if "minLength" in spec and len(value) < spec["minLength"]:
            return f"argument {key!r} below minLength {spec['minLength']}"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in spec and value < spec["minimum"]:
            return f"argument {key!r} below minimum {spec['minimum']}"
        if "maximum" in spec and value > spec["maximum"]:
            return f"argument {key!r} above maximum {spec['maximum']}"
    return None


class IdempotencyCache:
    """Per-session memoization keyed by (session, tool, canonical args)."""

    def __init__(self) -> None:
        self._store: dict[str, Any] = {}

    @staticmethod
    def key(ctx: ToolCtx, name: str, args: dict[str, Any]) -> str:
        canonical = json.dumps(args, sort_keys=True, default=str)
        return f"{ctx.session_id}:{name}:{canonical}"

    def has(self, key: str) -> bool:
        return key in self._store

    def get(self, key: str) -> Any:
        return self._store.get(key)

    def put(self, key: str, value: Any) -> None:
        self._store[key] = value


class Executor:
    def __init__(
        self,
        registry: ToolRegistry,
        *,
        audit_hook: AuditHook | None = None,
        idempotency: IdempotencyCache | None = None,
    ) -> None:
        self.registry = registry
        self.audit_hook = audit_hook
        self.cache = idempotency if idempotency is not None else IdempotencyCache()

    async def _audit(self, ctx: ToolCtx, spec: ToolSpec, args: dict, result: ToolResult) -> None:
        if self.audit_hook is not None:
            await self.audit_hook(ctx, spec, args, result)

    async def dispatch(self, name: str, args: dict[str, Any] | None, ctx: ToolCtx) -> ToolResult:
        args = args or {}
        spec = self.registry.get(name)
        if spec is None or not spec.enabled:
            return ToolResult(name, ok=False, status=DENIED, error="unknown or disabled tool")

        if not role_satisfies(ctx.role, spec.required_role):
            return ToolResult(name, ok=False, status=DENIED, error=f"role {ctx.role!r} cannot call {name!r}")

        err = validate_args(spec.params_schema, args)
        if err:
            return ToolResult(name, ok=False, status=ERROR, error=err)

        if spec.requires_approval:
            # Execution is deferred — the loop queues a PendingAction (#714).
            return ToolResult(name, ok=False, status=AWAITING_APPROVAL)

        if spec.requires_dry_run_first and not ctx.extra.get("dry_run_done"):
            return ToolResult(name, ok=False, status=DRY_RUN_REQUIRED, error="a dry-run must run first")

        cache_key = self.cache.key(ctx, name, args)
        if self.cache.has(cache_key):
            result = ToolResult(name, ok=True, status=OK, result=self.cache.get(cache_key), cached=True)
            await self._audit(ctx, spec, args, result)
            return result

        if spec.handler is None:
            return ToolResult(name, ok=False, status=ERROR, error="tool has no handler")

        try:
            value = await spec.handler(ctx, **args)
        except Exception as exc:  # noqa: BLE001 — surfaced to the loop as a tool error
            result = ToolResult(name, ok=False, status=ERROR, error=str(exc))
            await self._audit(ctx, spec, args, result)
            return result

        self.cache.put(cache_key, value)
        result = ToolResult(name, ok=True, status=OK, result=value)
        await self._audit(ctx, spec, args, result)
        return result
