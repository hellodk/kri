# fleet_platform/services/llm_context.py
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

INTENT_ADDENDUM: dict[str, str] = {
    "fleet_query": (
        "Answer the operator's question using ONLY the Fleet Snapshot and Node Records below. "
        "If the answer is not present in the provided context, say so explicitly — "
        "do not speculate or invent information. "
        "You cannot execute commands, scan nodes, or access live platform data beyond what is shown. "
        "Never claim to have performed a live action. "
        "If data is absent, tell the operator which specific data is missing and where they can find it in the kri UI."
    ),
    "salt_state": (
        "Generate a complete, production-ready SaltStack state file (.sls). "
        "Include only valid YAML. Wrap the file content in a ```sls code block."
    ),
    "ansible_playbook": (
        "Generate a complete, production-ready Ansible playbook (YAML). "
        "Target hosts should use 'all' unless the user specifies otherwise. "
        "Wrap the file content in a ```yaml code block."
    ),
    "fleet_command": (
        "Suggest the exact SaltStack execution module call to accomplish the request. "
        "Format: `salt '<target>' <module>.<function> [args]`. "
        "Explain what each argument does in one sentence."
    ),
    "explain": (
        "Explain the provided code in plain English. "
        "List: what it does, any side effects, and whether it is idempotent."
    ),
}

_GROUNDING_RULES = (
    "- Answer ONLY from the Fleet Snapshot and Node Records below. "
    "If a fact is not present, state that explicitly and stop — do not speculate.\n"
    "- You cannot execute commands, scan nodes, or perform live actions. "
    "Never claim to have done so.\n"
    "- When data is absent, name the missing data and tell the operator where to find it in the kri UI.\n"
)


def _sanitize_cell(value: str) -> str:
    """Escape pipe and newline characters that would break the LLM Markdown context table."""
    return value.replace("|", "\\|").replace("\n", " ").replace("\r", "")


def _format_last_seen(last_seen_at) -> str:
    if last_seen_at is None:
        return "never"
    now = datetime.now(UTC)
    if last_seen_at.tzinfo is None:
        last_seen_at = last_seen_at.replace(tzinfo=UTC)
    delta_s = int((now - last_seen_at).total_seconds())
    if delta_s < 120:
        return f"{delta_s}s ago"
    if delta_s < 3600:
        return f"{delta_s // 60}m ago"
    if delta_s < 86400:
        return f"{delta_s // 3600}h ago"
    return f"{delta_s // 86400}d ago"


def build_static_context(
    *,
    node_count: int,
    online_count: int,
    groups: list[str],
    salt_master: str,
    playbooks_dir: str,
    node_records: list[dict] | None = None,
) -> str:
    group_line = ", ".join(groups) if groups else "(none)"
    parts = [
        "You are an AI assistant embedded in **kri**, a build fleet management platform.\n\n"
        "## Fleet Snapshot\n"
        f"- Total nodes: {node_count}\n"
        f"- Online: {online_count}  |  Offline: {node_count - online_count}\n"
        "- Node OS: varies (Linux and macOS nodes supported)\n"
        f"- Salt master: {salt_master or 'not configured'}\n"
        f"- Playbooks directory: {playbooks_dir or 'not configured'}\n"
        f"- Groups: {group_line}\n"
    ]

    if node_records:
        parts.append("\n## Node Records\n")
        parts.append("| hostname | minion_id | ip | status | last_seen | group |\n")
        parts.append("|---|---|---|---|---|---|\n")
        for n in node_records:
            ip = n.get("ip") or "—"
            group = n.get("group") or "—"
            parts.append(
                f"| {_sanitize_cell(n['hostname'])} | {_sanitize_cell(n['minion_id'])} "
                f"| {_sanitize_cell(ip)} | {_sanitize_cell(n['status'])} "
                f"| {n['last_seen']} | {_sanitize_cell(group)} |\n"
            )

    parts.append(
        "\n## Rules\n"
        "- Never suggest commands that would destructively wipe filesystems.\n"
        "- Prefer idempotent operations.\n"
        "- When generating files, output only the file content — no extra prose before or after the code block.\n"
        + _GROUNDING_RULES
    )

    return "".join(parts)


async def build_fleet_context(db: AsyncSession, intent: str) -> str:
    """Fetch live fleet state and build a system prompt."""
    from fleet_platform.models.group import Group, GroupMember
    from fleet_platform.models.node import Node
    from fleet_platform.services.llm_svc import _redact_sensitive_data
    from fleet_platform.services.platform_settings_svc import (
        LLM_INCLUDE_NODE_IPS,
        PLAYBOOKS_DIR as PLAYBOOKS_DIR_KEY,
        SALT_MASTER as SALT_MASTER_KEY,
        get_settings_bulk,
    )

    node_count_result = await db.execute(select(func.count()).select_from(Node))
    node_count: int = node_count_result.scalar_one()

    online_result = await db.execute(select(func.count()).select_from(Node).where(Node.status == "online"))
    online_count: int = online_result.scalar_one()

    groups_result = await db.execute(select(Group.name).order_by(Group.name))
    groups: list[str] = list(groups_result.scalars().all())

    nodes_result = await db.execute(
        select(
            Node.id,
            Node.hostname,
            Node.minion_id,
            Node.ip_address,
            Node.status,
            Node.last_seen_at,
        ).order_by(Node.hostname).limit(50)
    )
    node_rows = nodes_result.all()

    membership_result = await db.execute(
        select(GroupMember.node_id, Group.name)
        .join(Group, Group.id == GroupMember.group_id)
    )
    node_group_map: dict = {str(row.node_id): row.name for row in membership_result.all()}

    ctx_settings = await get_settings_bulk(db, [SALT_MASTER_KEY, PLAYBOOKS_DIR_KEY, LLM_INCLUDE_NODE_IPS])
    salt_master = ctx_settings[SALT_MASTER_KEY] or ""
    playbooks_dir = ctx_settings[PLAYBOOKS_DIR_KEY] or ""
    include_ips = (ctx_settings[LLM_INCLUDE_NODE_IPS] or "true").lower() != "false"

    node_records = []
    for row in node_rows:
        node_records.append({
            "hostname": row.hostname or row.minion_id or "unknown",
            "minion_id": row.minion_id or "—",
            "ip": row.ip_address if include_ips else "[redacted]",
            "status": row.status or "unknown",
            "last_seen": _format_last_seen(row.last_seen_at),
            "group": node_group_map.get(str(row.id), "—"),
        })

    base = build_static_context(
        node_count=node_count,
        online_count=online_count,
        groups=groups,
        salt_master=salt_master,
        playbooks_dir=playbooks_dir,
        node_records=node_records,
    )
    addendum = INTENT_ADDENDUM.get(intent, INTENT_ADDENDUM["fleet_query"])
    context = f"{base}\n## Your Task\n{addendum}"

    return _redact_sensitive_data(context, include_ips=include_ips)
