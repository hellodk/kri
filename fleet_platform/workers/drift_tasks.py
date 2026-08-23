# fleet_platform/workers/drift_tasks.py
import logging
import time
import uuid
from datetime import UTC, datetime

from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy import select

from fleet_platform.db.session import get_sync_db
from fleet_platform.models.drift import DriftRecord
from fleet_platform.models.facts import NodeFact
from fleet_platform.models.node import Node
from fleet_platform.services.baseline_loader import find_baseline_for_node_sync
from fleet_platform.services.drift_engine import compute_drift as engine_compute_drift
from fleet_platform.services.task_lock import unique_task
from fleet_platform.workers.celery_app import celery_app
from fleet_platform.workers.salt_tasks import _run_salt_api

logger = logging.getLogger(__name__)

# Politeness gap between per-node pkg/service queries so a large fleet does not
# stampede salt-api with back-to-back /run requests (#1049 item 2).
_COLLECT_STAGGER_SECONDS = 0.25


@celery_app.task(
    name="fleet_platform.workers.drift_tasks.compute_drift",
    bind=True,
    max_retries=3,
    queue="drift",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
)
@unique_task(key_fn=lambda args, kwargs: f"compute_drift:{args[1] if len(args) > 1 else kwargs.get('node_id', '')}")
def compute_drift(self, node_id: str) -> dict:
    """Compute drift for a node and persist the result."""
    node_uuid = uuid.UUID(node_id)

    with get_sync_db() as db:
        # 1. Get latest grain facts
        fact = db.execute(
            select(NodeFact).where(NodeFact.node_id == node_uuid).order_by(NodeFact.collected_at.desc()).limit(1)
        ).scalar_one_or_none()

        if not fact:
            return {"node_id": node_id, "status": "no_facts"}

        # 2. Find applicable baseline (node > group > global)
        baseline = find_baseline_for_node_sync(node_uuid, db)
        if not baseline:
            return {"node_id": node_id, "status": "no_baseline"}

        # 3. Compute drift (pure function — no DB)
        result = engine_compute_drift(fact.grains, baseline.state_json)
        now = datetime.now(UTC)

        # 4. Persist drift record
        db.add(
            DriftRecord(
                node_id=node_uuid,
                baseline_id=baseline.id,
                computed_at=now,
                drift_score=result.drift_score,
                missing_packages=result.missing_packages,
                extra_packages=result.extra_packages,
                version_mismatches=result.version_mismatches,
                service_drift=result.service_drift,
                config_drift=result.config_drift,
            )
        )

        # 5. Update nodes.drift_score
        node = db.execute(select(Node).where(Node.id == node_uuid)).scalar_one_or_none()
        if node:
            node.drift_score = result.drift_score

        db.commit()

    return {
        "node_id": node_id,
        "status": "computed",
        "drift_score": result.drift_score,
    }


@celery_app.task(
    name="fleet_platform.workers.drift_tasks.collect_package_service_facts",
    queue="drift",
)
@unique_task(ttl=3600)  # singleton guard — a sweep must not overlap itself (#1048 pattern)
def collect_package_service_facts() -> dict:
    """Periodic (6h): refresh the drift-engine inputs for all online nodes.

    ``compute_drift`` reads ``pkgs``/``brew_pkgs`` and ``services`` from the
    latest NodeFact row, but nothing populated them after enrollment, so
    version/service drift was computed against stale data (#1049 item 2).
    This sweep queries every online minion via salt-api (``pkg.list_pkgs``,
    ``service.get_all``, one polite call pair per node), merges the results
    into that node's latest grains, and appends a fresh NodeFact — the same
    storage ``compute_drift`` reads. Each updated node then gets its
    ``compute_drift`` task dispatched so scores refresh immediately.
    """
    try:
        with get_sync_db() as db:
            rows = (
                db.execute(select(Node).where(Node.status == "online").where(Node.minion_id.isnot(None)))
                .scalars()
                .all()
            )
            targets = [(str(n.id), n.minion_id) for n in rows]

        updated: list[str] = []
        skipped: list[str] = []
        for node_id_str, minion_id in targets:
            pkgs_res = _run_salt_api(function="pkg.list_pkgs", target=minion_id, timeout=60)
            services_res = _run_salt_api(function="service.get_all", target=minion_id, timeout=60)

            pkgs = pkgs_res.get("result", [{}])
            services = services_res.get("result", [{}])
            pkgs = (pkgs[0] if pkgs else {}).get(minion_id) if pkgs_res.get("status") == "ok" else None
            services = (services[0] if services else {}).get(minion_id) if services_res.get("status") == "ok" else None
            if not isinstance(pkgs, dict) or not isinstance(services, list):
                skipped.append(minion_id)
                time.sleep(_COLLECT_STAGGER_SECONDS)
                continue

            with get_sync_db() as fdb:
                latest = fdb.execute(
                    select(NodeFact)
                    .where(NodeFact.node_id == uuid.UUID(node_id_str))
                    .order_by(NodeFact.collected_at.desc())
                    .limit(1)
                ).scalar_one_or_none()
                merged = dict(latest.grains) if latest and isinstance(latest.grains, dict) else {}
                merged["pkgs"] = pkgs
                merged["services"] = services
                fdb.add(NodeFact(node_id=uuid.UUID(node_id_str), collected_at=datetime.now(UTC), grains=merged))
                fdb.commit()

            celery_app.send_task("fleet_platform.workers.drift_tasks.compute_drift", args=[node_id_str], queue="drift")
            updated.append(minion_id)
            time.sleep(_COLLECT_STAGGER_SECONDS)

        return {"status": "ok", "nodes": len(targets), "updated": len(updated), "skipped": len(skipped)}
    except SoftTimeLimitExceeded:
        # Log + clean exit — no DB status to update for fact collection (#471 pattern)
        logger.warning("collect_package_service_facts: soft time limit exceeded — clean exit")
        return {"status": "timeout", "updated": 0, "skipped": 0}
