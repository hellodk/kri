# fleet_platform/services/process_stats_svc.py
"""Persistence for per-process telemetry samples (#598, EPIC #597)."""

import logging
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.models.node import Node
from fleet_platform.models.node_process_stat import NodeProcessStat
from fleet_platform.schemas.ingest import ProcessStatItem

logger = logging.getLogger(__name__)


async def persist_process_stats(
    db: AsyncSession,
    node: Node,
    processes: list[ProcessStatItem],
    collected_at: datetime,
) -> int:
    """Bulk-insert process samples for a node at ``collected_at``.

    Mirrors the existing ingest persistence pattern (add rows, single commit).
    Returns the number of rows inserted.
    """
    rows = [
        NodeProcessStat(
            node_id=node.id,
            collected_at=collected_at,
            pid=p.pid,
            name=p.name,
            cmdline=p.cmdline,
            cpu_pct=p.cpu_pct,
            mem_rss_bytes=p.mem_rss_bytes,
            mem_pct=p.mem_pct,
            num_threads=p.num_threads,
            status=p.status,
            username=p.username,
            io_read_bytes=p.io_read_bytes,
            io_write_bytes=p.io_write_bytes,
            is_llm=p.is_llm,
        )
        for p in processes
    ]
    db.add_all(rows)
    await db.commit()
    logger.debug("persisted %d process stats for node %s", len(rows), node.id)
    return len(rows)
