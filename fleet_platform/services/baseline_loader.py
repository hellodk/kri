# fleet_platform/services/baseline_loader.py
"""Load baseline YAML files and find applicable baselines for nodes."""

import uuid
from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from fleet_platform.models.drift import DesiredStateBaseline
from fleet_platform.models.group import GroupMember

_VALID_TARGET_TYPES = {"global", "group", "node"}


def load_baseline_yaml(path: str | Path) -> dict:
    """Parse a YAML baseline file. Returns the dict."""
    with open(path) as f:
        return yaml.safe_load(f)


def validate_baseline(data: dict) -> list[str]:
    """Return a list of validation error strings. Empty = valid."""
    errors = []
    if "name" not in data:
        errors.append("missing required field: name")
    target_type = data.get("target_type", "global")
    if target_type not in _VALID_TARGET_TYPES:
        errors.append(f"target_type must be one of {sorted(_VALID_TARGET_TYPES)}, got '{target_type}'")
    has_content = any(k in data for k in ("packages", "services", "configs"))
    if not has_content:
        errors.append("baseline must define at least one of: packages, services, configs")
    return errors


async def find_baseline_for_node(node_id: uuid.UUID, db: AsyncSession) -> DesiredStateBaseline | None:
    """Return the most specific applicable baseline for a node.

    Priority: node-specific > group-specific > global
    """
    # 1. Node-specific baseline
    result = await db.execute(
        select(DesiredStateBaseline)
        .where(DesiredStateBaseline.target_type == "node")
        .where(DesiredStateBaseline.target_id == node_id)
        .order_by(DesiredStateBaseline.version.desc())
        .limit(1)
    )
    if baseline := result.scalar_one_or_none():
        return baseline

    # 2. Group-specific (any group the node belongs to)
    result = await db.execute(
        select(DesiredStateBaseline)
        .join(GroupMember, GroupMember.group_id == DesiredStateBaseline.target_id)
        .where(DesiredStateBaseline.target_type == "group")
        .where(GroupMember.node_id == node_id)
        .order_by(DesiredStateBaseline.version.desc())
        .limit(1)
    )
    if baseline := result.scalar_one_or_none():
        return baseline

    # 3. Global baseline
    result = await db.execute(
        select(DesiredStateBaseline)
        .where(DesiredStateBaseline.target_type == "global")
        .order_by(DesiredStateBaseline.version.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


def find_baseline_for_node_sync(node_id: uuid.UUID, db: Session) -> DesiredStateBaseline | None:
    """Sync version of find_baseline_for_node for use in Celery workers."""
    baseline = db.execute(
        select(DesiredStateBaseline)
        .where(DesiredStateBaseline.target_type == "node")
        .where(DesiredStateBaseline.target_id == node_id)
        .order_by(DesiredStateBaseline.version.desc())
        .limit(1)
    ).scalar_one_or_none()
    if baseline:
        return baseline

    baseline = db.execute(
        select(DesiredStateBaseline)
        .join(GroupMember, GroupMember.group_id == DesiredStateBaseline.target_id)
        .where(DesiredStateBaseline.target_type == "group")
        .where(GroupMember.node_id == node_id)
        .order_by(DesiredStateBaseline.version.desc())
        .limit(1)
    ).scalar_one_or_none()
    if baseline:
        return baseline

    return db.execute(
        select(DesiredStateBaseline)
        .where(DesiredStateBaseline.target_type == "global")
        .order_by(DesiredStateBaseline.version.desc())
        .limit(1)
    ).scalar_one_or_none()
