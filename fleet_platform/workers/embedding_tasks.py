"""Celery tasks for background re-embedding of fleet knowledge.

Schedule:
  reindex_nodes          — every 5 min (node status changes)
  reindex_playbooks      — every 15 min (playbook file changes)
  reindex_drift_history  — every 5 min (new drift records)
"""
from pathlib import Path

from fleet_platform.workers.celery_app import celery_app


@celery_app.task(name="fleet_platform.workers.embedding_tasks.reindex_nodes")
def reindex_nodes() -> dict:
    """Embed one chunk per node — re-embed only if content_hash changed."""
    import asyncio

    from sqlalchemy import select

    from fleet_platform.db.session import AsyncSessionLocal as async_session_factory
    from fleet_platform.models.group import Group, GroupMember
    from fleet_platform.models.node import Node
    from fleet_platform.services.embedding_svc import chunk_node, upsert_chunks
    from fleet_platform.services.llm_context import _format_last_seen
    from fleet_platform.services.platform_settings_svc import (
        LLM_EMBED_BASE_URL,
        get_settings_bulk,
    )

    async def _run():
        async with async_session_factory() as db:
            settings = await get_settings_bulk(db, [LLM_EMBED_BASE_URL])
            embed_url = settings.get(LLM_EMBED_BASE_URL) or ""
            if not embed_url:
                return {"skipped": "no embed_base_url configured"}

            nodes = (await db.execute(select(Node))).scalars().all()
            membership = (
                await db.execute(
                    select(GroupMember.node_id, Group.name).join(
                        Group, Group.id == GroupMember.group_id
                    )
                )
            ).all()
            node_group = {str(r.node_id): r.name for r in membership}

            all_chunks = []
            for node in nodes:
                chunks = chunk_node(
                    node_id=str(node.id),
                    hostname=node.hostname or node.minion_id or "",
                    ip=node.ip_address or "",
                    status=node.status or "unknown",
                    group=node_group.get(str(node.id), ""),
                    os_info="",
                    last_seen=_format_last_seen(node.last_seen_at),
                )
                all_chunks.extend(chunks)

            upserted = await upsert_chunks(db, all_chunks, embed_url)
            return {"upserted": upserted, "total": len(all_chunks)}

    return asyncio.run(_run())


@celery_app.task(name="fleet_platform.workers.embedding_tasks.reindex_playbooks")
def reindex_playbooks() -> dict:
    """Embed per-play chunks for all playbooks in the configured directory."""
    import asyncio

    from fleet_platform.db.session import AsyncSessionLocal as async_session_factory
    from fleet_platform.services.embedding_svc import chunk_playbook, upsert_chunks
    from fleet_platform.services.platform_settings_svc import (
        LLM_EMBED_BASE_URL,
        get_settings_bulk,
    )
    from fleet_platform.services.platform_settings_svc import PLAYBOOKS_DIR as PLAYBOOKS_DIR_KEY

    async def _run():
        async with async_session_factory() as db:
            settings = await get_settings_bulk(db, [LLM_EMBED_BASE_URL, PLAYBOOKS_DIR_KEY])
            embed_url = settings.get(LLM_EMBED_BASE_URL) or ""
            playbooks_dir = settings.get(PLAYBOOKS_DIR_KEY) or ""
            if not embed_url or not playbooks_dir:
                return {"skipped": "missing embed_base_url or playbooks_dir"}

            all_chunks = []
            for yml_path in Path(playbooks_dir).glob("**/*.yml"):
                # Skip role task files — they are not top-level playbooks
                if "roles" in yml_path.parts:
                    continue
                try:
                    content = yml_path.read_text()
                    rel = str(yml_path.relative_to(playbooks_dir))
                    all_chunks.extend(chunk_playbook(f"playbooks/{rel}", content))
                except Exception:
                    continue

            upserted = await upsert_chunks(db, all_chunks, embed_url)
            return {"upserted": upserted, "total": len(all_chunks)}

    return asyncio.run(_run())


@celery_app.task(name="fleet_platform.workers.embedding_tasks.reindex_drift_history")
def reindex_drift_history() -> dict:
    """Embed drift records from the last 7 days."""
    import asyncio
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import select

    from fleet_platform.db.session import AsyncSessionLocal as async_session_factory
    from fleet_platform.models.drift import DriftRecord
    from fleet_platform.models.node import Node
    from fleet_platform.services.embedding_svc import chunk_drift_record, upsert_chunks
    from fleet_platform.services.platform_settings_svc import (
        LLM_EMBED_BASE_URL,
        get_settings_bulk,
    )

    async def _run():
        async with async_session_factory() as db:
            settings = await get_settings_bulk(db, [LLM_EMBED_BASE_URL])
            embed_url = settings.get(LLM_EMBED_BASE_URL) or ""
            if not embed_url:
                return {"skipped": "no embed_base_url configured"}

            cutoff = datetime.now(UTC) - timedelta(days=7)
            rows = (
                await db.execute(
                    select(DriftRecord, Node.hostname)
                    .join(Node, Node.id == DriftRecord.node_id)
                    .where(DriftRecord.computed_at >= cutoff)
                    .order_by(DriftRecord.computed_at.desc())
                    .limit(500)
                )
            ).all()

            all_chunks = []
            for drift, hostname in rows:
                all_chunks.extend(
                    chunk_drift_record(
                        drift_id=str(drift.id),
                        node_hostname=hostname or "",
                        computed_at=str(drift.computed_at),
                        drift_score=drift.drift_score,
                        missing_packages=drift.missing_packages or [],
                        extra_packages=drift.extra_packages or [],
                        version_mismatches=drift.version_mismatches or [],
                    )
                )

            upserted = await upsert_chunks(db, all_chunks, embed_url)
            return {"upserted": upserted, "total": len(all_chunks)}

    return asyncio.run(_run())
