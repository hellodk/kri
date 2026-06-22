"""Read-only agent tools #1–#11 (#711).

Each tool is a :class:`ToolSpec` whose handler is an ``async def(ctx, **args)``
coroutine wired to a real fleet service. Every tool here is side-effect
``read`` or ``execute_read`` — none mutate live state, so none gate on approval.
Handlers return JSON-serializable values (dict / list / str) because the result
is streamed over SSE and written to the audit row.

Salt and playbook primitives are synchronous (Celery worker helpers / disk IO);
they are wrapped with ``asyncio.to_thread`` so the event loop is never blocked.

``build_default_registry()`` assembles the catalogue the route hands to the
executor. The registry filters by role, so a viewer never sees admin tools.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload

from fleet_platform.agent.registry import ToolCtx, ToolRegistry, ToolSpec

# Salt functions the agent may invoke via run_salt_cmd. This is intersected with
# the platform allowlist at dispatch time — both gates must pass. cmd.run and any
# state-changing function are deliberately excluded: this is the read-only tier.
_AGENT_SALT_READONLY: frozenset[str] = frozenset(
    {
        "test.ping",
        "grains.items",
        "grains.get",
        "status.uptime",
        "status.loadavg",
        "disk.usage",
        "service.get_all",
        "service.status",
        "pkg.list_pkgs",
        "network.interfaces",
    }
)

_MAX_LIMIT = 100


def _node_to_dict(node: Any) -> dict[str, Any]:
    """Project a Node ORM row to a compact, JSON-safe summary for the model."""
    return {
        "id": str(node.id),
        "minion_id": node.minion_id,
        "hostname": node.hostname,
        "ip_address": str(node.ip_address) if node.ip_address else None,
        "os_version": node.os_version,
        "status": node.status,
        "drift_score": node.drift_score,
        "cpu_usage_pct": node.cpu_usage_pct,
        "mem_usage_pct": node.mem_usage_pct,
        "bootstrap_status": node.bootstrap_status,
        "maintenance_mode": node.maintenance_mode,
        "last_seen_at": node.last_seen_at.isoformat() if node.last_seen_at else None,
    }


# ---------------------------------------------------------------------------
# 1. list_nodes
# ---------------------------------------------------------------------------
async def _list_nodes(ctx: ToolCtx, status: str | None = None, search: str | None = None, limit: int = 25) -> Any:
    from fleet_platform.models.node import Node

    limit = max(1, min(int(limit), _MAX_LIMIT))
    query = select(Node)
    if status:
        query = query.where(Node.status == status)
    if search:
        pat = f"%{search}%"
        query = query.where(or_(Node.hostname.ilike(pat), Node.minion_id.ilike(pat)))
    query = query.order_by(Node.drift_score.desc()).limit(limit)
    rows = (await ctx.db.execute(query)).scalars().all()
    return {"count": len(rows), "nodes": [_node_to_dict(n) for n in rows]}


# ---------------------------------------------------------------------------
# 2. get_node
# ---------------------------------------------------------------------------
async def _get_node(ctx: ToolCtx, identifier: str) -> Any:
    from fleet_platform.models.node import Node

    clauses = [Node.hostname == identifier, Node.minion_id == identifier]
    try:
        clauses.append(Node.id == uuid.UUID(identifier))
    except (ValueError, AttributeError):
        pass
    query = select(Node).options(selectinload(Node.tags)).where(or_(*clauses)).limit(1)
    node = (await ctx.db.execute(query)).scalar_one_or_none()
    if node is None:
        return {"found": False, "identifier": identifier}
    data = _node_to_dict(node)
    data["found"] = True
    data["tags"] = [{"key": t.key, "value": t.value} for t in getattr(node, "tags", []) or []]
    return data


# ---------------------------------------------------------------------------
# 3. get_recent_audit
# ---------------------------------------------------------------------------
async def _get_recent_audit(ctx: ToolCtx, actor: str | None = None, action: str | None = None, limit: int = 25) -> Any:
    from fleet_platform.models.audit import AuditEvent

    limit = max(1, min(int(limit), _MAX_LIMIT))
    query = select(AuditEvent)
    if actor:
        query = query.where(AuditEvent.actor.ilike(f"%{actor}%"))
    if action:
        query = query.where(AuditEvent.action.ilike(f"%{action}%"))
    query = query.order_by(AuditEvent.event_at.desc()).limit(limit)
    rows = (await ctx.db.execute(query)).scalars().all()
    return {
        "count": len(rows),
        "events": [
            {
                "event_at": r.event_at.isoformat() if r.event_at else None,
                "actor": r.actor,
                "action": r.action,
                "resource_type": r.resource_type,
                "resource_id": str(r.resource_id) if r.resource_id else None,
            }
            for r in rows
        ],
    }


# ---------------------------------------------------------------------------
# Playbook dir resolution (shared by read_playbook / search_playbooks)
# ---------------------------------------------------------------------------
async def _resolve_playbook_roots(ctx: ToolCtx):
    from pathlib import Path

    from fleet_platform.services.platform_settings_svc import get_playbooks_dir, get_setting
    from fleet_platform.services.playbook_sources import get_all_playbook_dirs

    playbooks_dir = await get_playbooks_dir(ctx.db)
    try:
        sources_json = await get_setting(ctx.db, "playbook_sources")
    except Exception:  # noqa: BLE001 — degrade to builtin dir only
        sources_json = None
    roots: list[Path] = [d.resolve() for d in get_all_playbook_dirs(sources_json, playbooks_dir)]
    return playbooks_dir, roots


# ---------------------------------------------------------------------------
# 4. read_playbook
# ---------------------------------------------------------------------------
async def _read_playbook(ctx: ToolCtx, path: str) -> Any:
    from pathlib import Path

    playbooks_dir, roots = await _resolve_playbook_roots(ctx)
    target = (Path(playbooks_dir) / path).resolve()
    if not any(_is_relative_to(target, r) for r in roots):
        raise ValueError("path is outside the configured playbook roots")
    if not target.is_file():
        return {"found": False, "path": path}

    def _read() -> str:
        return target.read_text(errors="replace")

    content = await asyncio.to_thread(_read)
    if len(content) > 20000:
        content = content[:20000] + "\n... [truncated]"
    return {"found": True, "path": path, "content": content, "size": len(content)}


def _is_relative_to(child, parent) -> bool:
    try:
        return child.is_relative_to(parent)
    except AttributeError:  # py<3.9 safety; repo is 3.11 so unused
        return str(child).startswith(str(parent))


# ---------------------------------------------------------------------------
# 5. search_playbooks
# ---------------------------------------------------------------------------
async def _search_playbooks(ctx: ToolCtx, query: str, limit: int = 20) -> Any:
    from fleet_platform.services.playbook_discovery import discover_all

    playbooks_dir, _roots = await _resolve_playbook_roots(ctx)
    entries = await asyncio.to_thread(discover_all, playbooks_dir)
    q = query.lower()
    limit = max(1, min(int(limit), _MAX_LIMIT))
    matches = [
        {
            "filename": e.filename,
            "name": e.name,
            "description": e.description,
            "entry_type": e.entry_type,
        }
        for e in entries
        if q in (e.name or "").lower() or q in (e.filename or "").lower() or q in (e.description or "").lower()
    ]
    return {"count": len(matches[:limit]), "matches": matches[:limit]}


# ---------------------------------------------------------------------------
# 6. rag_search
# ---------------------------------------------------------------------------
async def _rag_search(ctx: ToolCtx, query: str, top_k: int = 8, source_types: list[str] | None = None) -> Any:
    from fleet_platform.services.embedding_svc import retrieve
    from fleet_platform.services.platform_settings_svc import LLM_EMBED_BASE_URL, get_setting

    embed_url = await get_setting(ctx.db, LLM_EMBED_BASE_URL)
    if not embed_url:
        return {"error": "RAG embedding endpoint is not configured (LLM_EMBED_BASE_URL).", "results": []}
    top_k = max(1, min(int(top_k), 20))
    chunks = await retrieve(ctx.db, query, embed_url, source_types=source_types, top_k=top_k)
    return {
        "count": len(chunks),
        "results": [
            {
                "source_type": c.get("source_type"),
                "source_id": c.get("source_id"),
                "chunk_text": (c.get("chunk_text") or "")[:1500],
            }
            for c in chunks
        ],
    }


# ---------------------------------------------------------------------------
# 7. embed_text
# ---------------------------------------------------------------------------
async def _embed_text(ctx: ToolCtx, text: str) -> Any:
    from fleet_platform.services.embedding_svc import embed_texts
    from fleet_platform.services.platform_settings_svc import LLM_EMBED_BASE_URL, get_setting

    embed_url = await get_setting(ctx.db, LLM_EMBED_BASE_URL)
    if not embed_url:
        return {"error": "RAG embedding endpoint is not configured (LLM_EMBED_BASE_URL)."}
    vectors = await embed_texts([text], embed_url, mode="query")
    vec = vectors[0] if vectors else []
    return {"dim": len(vec), "preview": vec[:8]}


# ---------------------------------------------------------------------------
# 8–10. Salt tools (ping / cmd / state dry-run) — all via the low-level HTTP API
# ---------------------------------------------------------------------------
async def _ping_node(ctx: ToolCtx, minion_id: str) -> Any:
    from fleet_platform.workers.salt_tasks import _run_salt_api

    return await asyncio.to_thread(_run_salt_api, "test.ping", minion_id)


async def _run_salt_cmd(ctx: ToolCtx, function: str, minion_id: str, args: list[str] | None = None) -> Any:
    import json as _json

    from fleet_platform.services.platform_settings_svc import (
        _DEFAULT_SALT_FUNCTIONS,
        _SALT_MINIMUM_FUNCTIONS,
        SALT_ALLOWED_FUNCTIONS,
        get_setting,
    )
    from fleet_platform.workers.salt_tasks import _run_salt_api

    raw = await get_setting(ctx.db, SALT_ALLOWED_FUNCTIONS)
    if raw:
        try:
            platform_allowed = frozenset(_json.loads(raw)) | _SALT_MINIMUM_FUNCTIONS
        except (ValueError, TypeError):
            platform_allowed = _DEFAULT_SALT_FUNCTIONS | _SALT_MINIMUM_FUNCTIONS
    else:
        platform_allowed = _DEFAULT_SALT_FUNCTIONS | _SALT_MINIMUM_FUNCTIONS

    # Both gates must pass: the platform allowlist AND the agent read-only subset.
    if function not in platform_allowed or function not in _AGENT_SALT_READONLY:
        raise ValueError(
            f"function {function!r} is not permitted for the agent; "
            f"allowed read-only functions: {sorted(_AGENT_SALT_READONLY)}"
        )
    return await asyncio.to_thread(_run_salt_api, function, minion_id, args)


async def _apply_salt_state_dry_run(ctx: ToolCtx, state: str, minion_id: str) -> Any:
    from fleet_platform.workers.salt_tasks import _run_salt_api

    # state.apply <state> test=True — dry-run only, never mutates the minion.
    return await asyncio.to_thread(_run_salt_api, "state.apply", minion_id, [state], {"test": True})


# ---------------------------------------------------------------------------
# 11. lint_artifact
# ---------------------------------------------------------------------------
async def _lint_artifact(ctx: ToolCtx, content: str) -> Any:
    import yaml

    try:
        loaded = yaml.safe_load(content)
    except yaml.YAMLError as exc:
        return {"valid": False, "error": str(exc).splitlines()[0] if str(exc) else "invalid YAML"}
    warnings: list[str] = []
    if isinstance(loaded, list):
        for i, play in enumerate(loaded):
            if isinstance(play, dict) and "hosts" not in play and "import_playbook" not in play:
                warnings.append(f"play[{i}] has no 'hosts' or 'import_playbook' key")
    return {"valid": True, "top_level_type": type(loaded).__name__, "warnings": warnings}


# ---------------------------------------------------------------------------
# 12–14. Authoring tools (write-quarantine) + artifact dry-run (#713)
# ---------------------------------------------------------------------------
async def _author_artifact(ctx: ToolCtx, kind: str, filename: str, content: str) -> Any:
    from fleet_platform.services import agent_quarantine as q
    from fleet_platform.services.artifact_validation import validate_artifact

    if ctx.session_id is None:
        raise ValueError("authoring requires an agent session")
    result = validate_artifact(content, kind)
    if not result.valid:
        # Rejected content never touches quarantine — validation is a hard gate.
        return {"written": False, "validation": result.as_dict()}
    meta = await asyncio.to_thread(
        q.write_artifact,
        ctx.actor,
        ctx.session_id,
        filename,
        content,
        metadata={"kind": kind, "created_by": ctx.actor},
    )
    return {"written": True, "artifact": meta, "validation": result.as_dict()}


async def _generate_ansible_playbook(ctx: ToolCtx, filename: str, content: str) -> Any:
    return await _author_artifact(ctx, "ansible_playbook", filename, content)


async def _generate_salt_state(ctx: ToolCtx, filename: str, content: str) -> Any:
    return await _author_artifact(ctx, "salt_state", filename, content)


async def _dry_run_artifact(ctx: ToolCtx, filename: str) -> Any:
    """Local dry-run of a quarantined artifact: re-validate + render summary.

    This is a master-free dry-run (no minion execution): it confirms the
    quarantined content still parses/validates and reports the structural plan
    (play/state count). Live minion dry-runs are gated in Phase E.
    """
    from fleet_platform.services import agent_quarantine as q
    from fleet_platform.services.artifact_validation import validate_artifact

    if ctx.session_id is None:
        raise ValueError("dry-run requires an agent session")
    content, meta = await asyncio.to_thread(q.read_artifact, ctx.actor, ctx.session_id, filename)
    kind = (meta.get("metadata") or {}).get("kind") or "ansible_playbook"
    result = validate_artifact(content, kind)
    plan = None
    if result.valid and result.parsed is not None:
        if kind == "ansible_playbook" and isinstance(result.parsed, list):
            plan = {"plays": len(result.parsed)}
        elif kind == "salt_state" and isinstance(result.parsed, dict):
            plan = {"states": len([k for k in result.parsed if k != "include"])}
    return {"filename": filename, "kind": kind, "validation": result.as_dict(), "plan": plan}


# ---------------------------------------------------------------------------
# 15–19. Live apply / control tools (#714) — write-live, dry-run + approval.
# These handlers ONLY run via Executor.dispatch_approved after human sign-off;
# guards (PROTECTED_TARGETS / planner-self-deplane) are enforced at propose and
# execute time. ctx.actor is always the original operator.
# ---------------------------------------------------------------------------
async def _apply_salt_state(ctx: ToolCtx, minion_id: str, state: str) -> Any:
    from fleet_platform.workers.salt_tasks import _run_salt_api

    # Live state.apply (no test=True) — gated upstream by approval + prior dry-run.
    return await asyncio.to_thread(_run_salt_api, "state.apply", minion_id, [state])


async def _restart_service(ctx: ToolCtx, minion_id: str, service: str) -> Any:
    from fleet_platform.workers.salt_tasks import _run_salt_api

    return await asyncio.to_thread(_run_salt_api, "service.restart", minion_id, [service])


async def _set_pillar(ctx: ToolCtx, minion_id: str, pillar_key: str, value: str) -> Any:
    """Refresh a minion's pillar after a promoted pillar change.

    Pillar *content* is authored via the quarantine→promote path; this live tool
    records the intended key/value (audited) and triggers a pillar refresh so the
    minion re-fetches it. It never injects arbitrary master-side state.
    """
    from fleet_platform.workers.salt_tasks import _run_salt_api

    refreshed = await asyncio.to_thread(_run_salt_api, "saltutil.refresh_pillar", minion_id)
    return {"pillar_key": pillar_key, "value": value, "refreshed": refreshed}


async def _bootstrap_node(ctx: ToolCtx, minion_id: str) -> Any:
    from fleet_platform.workers.salt_tasks import _run_salt_api

    # Apply the bootstrap state set live on a freshly-accepted minion.
    return await asyncio.to_thread(_run_salt_api, "state.apply", minion_id, ["bootstrap"])


async def _enable_node(ctx: ToolCtx, minion_id: str) -> Any:
    from fleet_platform.models.node import Node

    if ctx.db is None:
        raise ValueError("enable_node requires a db session")
    node = (await ctx.db.execute(select(Node).where(Node.minion_id == minion_id))).scalar_one_or_none()
    if node is None:
        raise ValueError(f"node {minion_id!r} not found")
    node.status = "active"
    await ctx.db.commit()
    return {"minion_id": minion_id, "status": "active"}


# ---------------------------------------------------------------------------
# Registry assembly
# ---------------------------------------------------------------------------
def _obj_schema(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
        "additionalProperties": False,
    }


def build_default_registry() -> ToolRegistry:
    """Build the read-only tool catalogue for the Phase B agent MVP."""
    reg = ToolRegistry()

    reg.register(
        ToolSpec(
            name="list_nodes",
            description="List fleet nodes, optionally filtered by status or a hostname/minion_id search term.",
            params_schema=_obj_schema(
                {
                    "status": {"type": "string", "description": "Filter by node status, e.g. 'degraded'."},
                    "search": {
                        "type": "string",
                        "maxLength": 200,
                        "description": "Substring match on hostname or minion_id.",
                    },
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100, "description": "Max rows (default 25)."},
                }
            ),
            required_role="viewer",
            side_effect="read",
            handler=_list_nodes,
        )
    )
    reg.register(
        ToolSpec(
            name="get_node",
            description="Fetch a single node by UUID, hostname, or minion_id.",
            params_schema=_obj_schema(
                {"identifier": {"type": "string", "maxLength": 255, "description": "UUID, hostname, or minion_id."}},
                required=["identifier"],
            ),
            required_role="viewer",
            side_effect="read",
            handler=_get_node,
        )
    )
    reg.register(
        ToolSpec(
            name="get_recent_audit",
            description="Read recent audit-log events, optionally filtered by actor or action substring.",
            params_schema=_obj_schema(
                {
                    "actor": {"type": "string", "maxLength": 255},
                    "action": {"type": "string", "maxLength": 255},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                }
            ),
            required_role="admin",
            side_effect="read",
            handler=_get_recent_audit,
        )
    )
    reg.register(
        ToolSpec(
            name="read_playbook",
            description="Read the contents of an Ansible playbook or role file by its relative path.",
            params_schema=_obj_schema(
                {"path": {"type": "string", "maxLength": 500, "description": "Path relative to the playbooks dir."}},
                required=["path"],
            ),
            required_role="operator",
            side_effect="read",
            handler=_read_playbook,
        )
    )
    reg.register(
        ToolSpec(
            name="search_playbooks",
            description="Search available playbooks/roles by name, filename, or description.",
            params_schema=_obj_schema(
                {
                    "query": {"type": "string", "maxLength": 200},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                },
                required=["query"],
            ),
            required_role="viewer",
            side_effect="read",
            handler=_search_playbooks,
        )
    )
    reg.register(
        ToolSpec(
            name="rag_search",
            description="Semantic search over indexed fleet knowledge (nodes, playbooks, salt states, drift).",
            params_schema=_obj_schema(
                {
                    "query": {"type": "string", "maxLength": 1000},
                    "top_k": {"type": "integer", "minimum": 1, "maximum": 20},
                    "source_types": {"type": "array", "description": "Restrict to source types, e.g. ['playbook']."},
                },
                required=["query"],
            ),
            required_role="viewer",
            side_effect="read",
            handler=_rag_search,
        )
    )
    reg.register(
        ToolSpec(
            name="embed_text",
            description="Embed arbitrary text and return the vector dimension and a small preview.",
            params_schema=_obj_schema(
                {"text": {"type": "string", "maxLength": 4000}},
                required=["text"],
            ),
            required_role="operator",
            side_effect="read",
            handler=_embed_text,
        )
    )
    reg.register(
        ToolSpec(
            name="ping_node",
            description="Salt test.ping a minion to check live reachability.",
            params_schema=_obj_schema(
                {"minion_id": {"type": "string", "maxLength": 255}},
                required=["minion_id"],
            ),
            required_role="operator",
            side_effect="execute_read",
            handler=_ping_node,
        )
    )
    reg.register(
        ToolSpec(
            name="run_salt_cmd",
            description=(
                "Run an allowlisted read-only Salt function on a minion "
                "(e.g. grains.items, disk.usage, service.status)."
            ),
            params_schema=_obj_schema(
                {
                    "function": {"type": "string", "maxLength": 100},
                    "minion_id": {"type": "string", "maxLength": 255},
                    "args": {"type": "array", "description": "Positional args for the function."},
                },
                required=["function", "minion_id"],
            ),
            required_role="operator",
            side_effect="execute_read",
            handler=_run_salt_cmd,
        )
    )
    reg.register(
        ToolSpec(
            name="apply_salt_state_dry_run",
            description="Run a Salt state.apply in test=True (dry-run) mode — reports changes without applying them.",
            params_schema=_obj_schema(
                {
                    "state": {"type": "string", "maxLength": 255},
                    "minion_id": {"type": "string", "maxLength": 255},
                },
                required=["state", "minion_id"],
            ),
            required_role="operator",
            side_effect="execute_read",
            handler=_apply_salt_state_dry_run,
        )
    )
    reg.register(
        ToolSpec(
            name="lint_artifact",
            description="Validate YAML syntax of a playbook/state artifact and surface structural warnings.",
            params_schema=_obj_schema(
                {"content": {"type": "string", "maxLength": 20000}},
                required=["content"],
            ),
            required_role="operator",
            side_effect="read",
            handler=_lint_artifact,
        )
    )
    reg.register(
        ToolSpec(
            name="generate_ansible_playbook",
            description=(
                "Validate an Ansible playbook (YAML) and write it to the session quarantine. "
                "Never reaches the live tree — promotion is a separate admin action."
            ),
            params_schema=_obj_schema(
                {
                    "filename": {"type": "string", "maxLength": 128},
                    "content": {"type": "string", "maxLength": 65536},
                },
                required=["filename", "content"],
            ),
            required_role="operator",
            side_effect="write_quarantine",
            handler=_generate_ansible_playbook,
        )
    )
    reg.register(
        ToolSpec(
            name="generate_salt_state",
            description=(
                "Validate a Salt state (YAML) and write it to the session quarantine. "
                "Never reaches the live tree — promotion is a separate admin action."
            ),
            params_schema=_obj_schema(
                {
                    "filename": {"type": "string", "maxLength": 128},
                    "content": {"type": "string", "maxLength": 65536},
                },
                required=["filename", "content"],
            ),
            required_role="operator",
            side_effect="write_quarantine",
            handler=_generate_salt_state,
        )
    )
    reg.register(
        ToolSpec(
            name="dry_run_artifact",
            description="Re-validate a quarantined artifact and report its structural plan (play/state count).",
            params_schema=_obj_schema(
                {"filename": {"type": "string", "maxLength": 128}},
                required=["filename"],
            ),
            required_role="operator",
            side_effect="read",
            handler=_dry_run_artifact,
        )
    )
    reg.register(
        ToolSpec(
            name="apply_salt_state",
            description="Apply a Salt state live to a minion. Requires a prior dry-run and human approval.",
            params_schema=_obj_schema(
                {
                    "minion_id": {"type": "string", "maxLength": 200},
                    "state": {"type": "string", "maxLength": 200},
                },
                required=["minion_id", "state"],
            ),
            required_role="operator",
            side_effect="write_live",
            requires_approval=True,
            requires_dry_run_first=True,
            handler=_apply_salt_state,
        )
    )
    reg.register(
        ToolSpec(
            name="restart_service",
            description="Restart a service on a minion live. Requires human approval; protected services refused.",
            params_schema=_obj_schema(
                {
                    "minion_id": {"type": "string", "maxLength": 200},
                    "service": {"type": "string", "maxLength": 200},
                },
                required=["minion_id", "service"],
            ),
            required_role="operator",
            side_effect="write_live",
            requires_approval=True,
            handler=_restart_service,
        )
    )
    reg.register(
        ToolSpec(
            name="set_pillar",
            description="Refresh a minion's pillar for a promoted pillar key/value. Requires human approval.",
            params_schema=_obj_schema(
                {
                    "minion_id": {"type": "string", "maxLength": 200},
                    "pillar_key": {"type": "string", "maxLength": 200},
                    "value": {"type": "string", "maxLength": 2000},
                },
                required=["minion_id", "pillar_key", "value"],
            ),
            required_role="operator",
            side_effect="write_live",
            requires_approval=True,
            handler=_set_pillar,
        )
    )
    reg.register(
        ToolSpec(
            name="bootstrap_node",
            description="Apply the bootstrap state to a minion live. Requires a prior dry-run and human approval.",
            params_schema=_obj_schema(
                {"minion_id": {"type": "string", "maxLength": 200}},
                required=["minion_id"],
            ),
            required_role="operator",
            side_effect="write_live",
            requires_approval=True,
            requires_dry_run_first=True,
            handler=_bootstrap_node,
        )
    )
    reg.register(
        ToolSpec(
            name="enable_node",
            description="Mark a node active in the fleet inventory. Requires human approval.",
            params_schema=_obj_schema(
                {"minion_id": {"type": "string", "maxLength": 200}},
                required=["minion_id"],
            ),
            required_role="operator",
            side_effect="write_live",
            requires_approval=True,
            handler=_enable_node,
        )
    )
    return reg
