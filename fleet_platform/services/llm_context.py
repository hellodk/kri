# fleet_platform/services/llm_context.py
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

INTENT_ADDENDUM: dict[str, str] = {
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


def build_static_context(
    *,
    node_count: int,
    online_count: int,
    groups: list[str],
    salt_master: str,
    playbooks_dir: str,
) -> str:
    group_line = ", ".join(groups) if groups else "(none)"
    return (
        "You are an AI assistant embedded in **kri**, a build fleet management platform.\n\n"
        "## Fleet Snapshot\n"
        f"- Total nodes: {node_count}\n"
        f"- Online: {online_count}  |  Offline: {node_count - online_count}\n"
        "- Node OS: varies (Linux and macOS nodes supported)\n"
        f"- Salt master: {salt_master or 'not configured'}\n"
        f"- Playbooks directory: {playbooks_dir or 'not configured'}\n"
        f"- Groups: {group_line}\n\n"
        "## Rules\n"
        "- Never suggest commands that would destructively wipe filesystems.\n"
        "- Prefer idempotent operations.\n"
        "- When generating files, output only the file content — no extra prose before or after the code block.\n"
    )


async def build_fleet_context(db: AsyncSession, intent: str) -> str:
    """Fetch live fleet state and build a system prompt. Stays under ~1500 tokens."""
    from fleet_platform.models.group import Group
    from fleet_platform.models.node import Node
    from fleet_platform.services.llm_svc import _redact_sensitive_data
    from fleet_platform.services.platform_settings_svc import (
        LLM_INCLUDE_NODE_IPS,
        PLAYBOOKS_DIR as PLAYBOOKS_DIR_KEY,
        SALT_MASTER as SALT_MASTER_KEY,
        get_setting,
    )

    node_count_result = await db.execute(select(func.count()).select_from(Node))
    node_count: int = node_count_result.scalar_one()

    online_result = await db.execute(select(func.count()).select_from(Node).where(Node.status == "online"))
    online_count: int = online_result.scalar_one()

    groups_result = await db.execute(select(Group.name).order_by(Group.name))
    groups: list[str] = list(groups_result.scalars().all())

    salt_master = await get_setting(db, SALT_MASTER_KEY) or ""
    playbooks_dir = await get_setting(db, PLAYBOOKS_DIR_KEY) or ""

    base = build_static_context(
        node_count=node_count,
        online_count=online_count,
        groups=groups,
        salt_master=salt_master,
        playbooks_dir=playbooks_dir,
    )
    addendum = INTENT_ADDENDUM.get(intent, "")
    context = f"{base}\n## Your Task\n{addendum}"

    include_ips_setting = await get_setting(db, LLM_INCLUDE_NODE_IPS)
    include_ips = (include_ips_setting or "true").lower() != "false"
    return _redact_sensitive_data(context, include_ips=include_ips)
