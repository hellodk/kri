# fleet_platform/services/group_resolver.py
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.models.node import Node, Tag


def validate_predicate(predicate: dict) -> bool:
    """Return True if predicate has correct structure for a dynamic group."""
    conditions = predicate.get("and")
    if not conditions or not isinstance(conditions, list):
        return False
    for cond in conditions:
        if "key" not in cond or "value" not in cond:
            return False
    return True


async def resolve_dynamic_group(
    predicate: dict, db: AsyncSession
) -> list[uuid.UUID]:
    """Return node IDs matching all conditions in the predicate.

    Predicate format: {"and": [{"key": "env", "value": "prod"}, ...]}
    Empty or invalid predicate returns [].
    """
    if not validate_predicate(predicate):
        return []

    query = select(Node.id)
    for cond in predicate["and"]:
        subq = (
            select(Tag.node_id)
            .where(Tag.key == cond["key"])
            .where(Tag.value == cond["value"])
            .scalar_subquery()
        )
        query = query.where(Node.id.in_(subq))

    result = await db.execute(query)
    return [row[0] for row in result.fetchall()]
