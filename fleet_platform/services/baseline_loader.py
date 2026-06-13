# fleet_platform/services/baseline_loader.py
"""Load baseline YAML files and find applicable baselines for nodes."""

import uuid
from pathlib import Path
from typing import TYPE_CHECKING

import yaml
from sqlalchemy import case, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from fleet_platform.models.drift import DesiredStateBaseline
from fleet_platform.models.group import GroupMember

if TYPE_CHECKING:
    from fleet_platform.models.node import Node

_VALID_TARGET_TYPES = {"global", "group", "node"}
# Canonical OS families. Match what salt-master's `os_family` grain reports
# for cross-system consistency. None means OS-agnostic.
_VALID_OS_FAMILIES = {"Darwin", "Linux", "FreeBSD", "Windows"}


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
    os_family = data.get("os_family")
    if os_family is not None and os_family not in _VALID_OS_FAMILIES:
        errors.append(f"os_family must be one of {sorted(_VALID_OS_FAMILIES)} or omitted, got '{os_family}'")
    has_content = any(k in data for k in ("packages", "services", "configs"))
    if not has_content:
        errors.append("baseline must define at least one of: packages, services, configs")
    return errors


def derive_os_family(node: "Node") -> str | None:
    """Best-effort OS family inference from a Node row.

    Node has no first-class os_family column today; this maps from the
    fields we do collect (``macos_version``, ``os_version``) onto the same
    canonical labels Salt grains use ('Darwin', 'Linux', 'FreeBSD',
    'Windows'). Returns None when there is no clean signal — callers fall
    back to OS-agnostic baselines in that case (#prod-os-baselines).
    """
    # macos_version is set by the ios/macos collector and is the strongest
    # signal we have for Apple devices.
    if getattr(node, "macos_version", None):
        return "Darwin"

    raw = (getattr(node, "os_version", None) or "").lower().strip()
    if not raw:
        return None

    if "darwin" in raw or "macos" in raw or "mac os" in raw:
        return "Darwin"
    if "freebsd" in raw:
        return "FreeBSD"
    if "windows" in raw or raw.startswith("win"):
        return "Windows"
    # Linux distro tokens covering the families in scope. Order doesn't
    # matter — first match wins, and they all collapse to "Linux".
    linux_tokens = (
        "linux",
        "ubuntu",
        "debian",
        "centos",
        "rhel",
        "red hat",
        "fedora",
        "alpine",
        "arch",
        "rocky",
        "almalinux",
        "suse",
        "opensuse",
        "manjaro",
        "gentoo",
    )
    if any(tok in raw for tok in linux_tokens):
        return "Linux"
    return None


def _os_priority(os_fam: str | None):
    """SQL CASE expression giving exact-match os_family priority over NULL.

    With os_fam='Darwin':
      - rows where os_family='Darwin' get priority 0  (best)
      - rows where os_family IS NULL  get priority 1
      - rows with a different os_family won't appear (filtered separately)
    With os_fam=None:
      - only NULL-os_family rows match the WHERE clause; CASE is moot.
    """
    if os_fam is None:
        # Constant — every matching row has the same priority.
        return case((DesiredStateBaseline.os_family.is_(None), 0), else_=0)
    return case(
        (DesiredStateBaseline.os_family == os_fam, 0),
        (DesiredStateBaseline.os_family.is_(None), 1),
        else_=2,
    )


def _os_filter(os_fam: str | None):
    """SQLAlchemy WHERE clause: only OS-agnostic rows OR rows matching os_fam."""
    if os_fam is None:
        return DesiredStateBaseline.os_family.is_(None)
    return DesiredStateBaseline.os_family.is_(None) | (DesiredStateBaseline.os_family == os_fam)


async def find_baseline_for_node(node_id: uuid.UUID, db: AsyncSession) -> DesiredStateBaseline | None:
    """Return the most specific applicable baseline for a node.

    Tier priority: node-specific > group-specific > global.
    Within each tier, OS-aware priority (#prod-os-baselines):
      1. baselines whose ``os_family`` matches the node's derived family
      2. OS-agnostic baselines (``os_family IS NULL``)
      3. baselines for a different OS are excluded entirely.
    Ties are broken by ``version DESC`` (latest first).
    """
    from fleet_platform.models.node import Node

    node = (await db.execute(select(Node).where(Node.id == node_id))).scalar_one_or_none()
    os_fam = derive_os_family(node) if node is not None else None

    # 1. Node-specific baseline
    result = await db.execute(
        select(DesiredStateBaseline)
        .where(DesiredStateBaseline.target_type == "node")
        .where(DesiredStateBaseline.target_id == node_id)
        .where(_os_filter(os_fam))
        .order_by(_os_priority(os_fam), DesiredStateBaseline.version.desc())
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
        .where(_os_filter(os_fam))
        .order_by(_os_priority(os_fam), DesiredStateBaseline.version.desc())
        .limit(1)
    )
    if baseline := result.scalar_one_or_none():
        return baseline

    # 3. Global baseline
    result = await db.execute(
        select(DesiredStateBaseline)
        .where(DesiredStateBaseline.target_type == "global")
        .where(_os_filter(os_fam))
        .order_by(_os_priority(os_fam), DesiredStateBaseline.version.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


def find_baseline_for_node_sync(node_id: uuid.UUID, db: Session) -> DesiredStateBaseline | None:
    """Sync version of find_baseline_for_node for use in Celery workers."""
    from fleet_platform.models.node import Node

    node = db.execute(select(Node).where(Node.id == node_id)).scalar_one_or_none()
    os_fam = derive_os_family(node) if node is not None else None

    baseline = db.execute(
        select(DesiredStateBaseline)
        .where(DesiredStateBaseline.target_type == "node")
        .where(DesiredStateBaseline.target_id == node_id)
        .where(_os_filter(os_fam))
        .order_by(_os_priority(os_fam), DesiredStateBaseline.version.desc())
        .limit(1)
    ).scalar_one_or_none()
    if baseline:
        return baseline

    baseline = db.execute(
        select(DesiredStateBaseline)
        .join(GroupMember, GroupMember.group_id == DesiredStateBaseline.target_id)
        .where(DesiredStateBaseline.target_type == "group")
        .where(GroupMember.node_id == node_id)
        .where(_os_filter(os_fam))
        .order_by(_os_priority(os_fam), DesiredStateBaseline.version.desc())
        .limit(1)
    ).scalar_one_or_none()
    if baseline:
        return baseline

    return db.execute(
        select(DesiredStateBaseline)
        .where(DesiredStateBaseline.target_type == "global")
        .where(_os_filter(os_fam))
        .order_by(_os_priority(os_fam), DesiredStateBaseline.version.desc())
        .limit(1)
    ).scalar_one_or_none()
