# fleet_platform/workers/drift_tasks.py
import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from fleet_platform.db.session import get_sync_db
from fleet_platform.models.drift import DriftRecord
from fleet_platform.models.facts import NodeFact
from fleet_platform.models.node import Node
from fleet_platform.services.baseline_loader import find_baseline_for_node_sync
from fleet_platform.services.drift_engine import compute_drift as engine_compute_drift
from fleet_platform.services.task_lock import unique_task
from fleet_platform.workers.celery_app import celery_app


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
