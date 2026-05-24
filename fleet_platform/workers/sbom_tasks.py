import json
import os
import uuid as _uuid

from sqlalchemy import delete, select, text

from fleet_platform.db.session import get_sync_db
from fleet_platform.models.sbom import SBOMComponent, SBOMScan
from fleet_platform.services.sbom_parser import SBOMParser
from fleet_platform.workers.celery_app import celery_app


@celery_app.task(
    name="fleet_platform.workers.sbom_tasks.index_sbom",
    bind=True,
    max_retries=3,
    queue="sbom",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
)
def index_sbom(self, node_id: str, file_path: str) -> dict:
    # Read and immediately delete the temp file
    try:
        with open(file_path) as f:
            content = f.read()
    except FileNotFoundError:
        return {"status": "error", "reason": "file_not_found"}
    finally:
        try:
            os.unlink(file_path)
        except OSError:
            pass

    try:
        raw_json = json.loads(content)
    except json.JSONDecodeError:
        return {"status": "error", "reason": "json_parse_error"}

    parser = SBOMParser()
    scan, components = parser.parse_cyclonedx(node_id, raw_json)

    with get_sync_db() as db:
        db.add(scan)
        db.flush()
        if components:
            db.bulk_insert_mappings(
                SBOMComponent,
                [{"scan_id": scan.id, "node_id": _uuid.UUID(node_id), **c} for c in components],
            )
        db.commit()

    archive_old_scans.delay(node_id=node_id, keep_count=3)
    return {"status": "indexed", "node_id": node_id, "component_count": len(components)}


@celery_app.task(
    name="fleet_platform.workers.sbom_tasks.index_sbom_from_grains",
    bind=True,
    max_retries=3,
    queue="sbom",
    autoretry_for=(Exception,),
    retry_backoff=True,
)
def index_sbom_from_grains(self, node_id: str) -> dict:
    """Build an SBOM from package data in the latest grain facts and index it."""
    from datetime import UTC, datetime
    from fleet_platform.models.facts import NodeFact

    node_uuid = _uuid.UUID(node_id)

    with get_sync_db() as db:
        fact = db.execute(
            select(NodeFact)
            .where(NodeFact.node_id == node_uuid)
            .order_by(NodeFact.collected_at.desc())
            .limit(1)
        ).scalar_one_or_none()

        if not fact:
            return {"status": "no_facts"}

        grains = fact.grains
        # Merge all package sources: Salt pkgs, Homebrew, pip
        pkgs: dict[str, str] = {}
        for key in ("pkgs", "brew_pkgs", "pip_pkgs"):
            val = grains.get(key)
            if isinstance(val, dict):
                pkgs.update(val)

        if not pkgs:
            return {"status": "no_packages"}

        # Build minimal CycloneDX-compatible structure for SBOMParser
        components = [
            {
                "name": name,
                "version": str(ver) if ver else None,
                "type": "library",
                "purl": f"pkg:brew/{name}@{ver}" if ver else f"pkg:brew/{name}",
                "licenses": [],
                "cpes": [],
            }
            for name, ver in pkgs.items()
        ]

        cyclonedx = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.4",
            "metadata": {
                "timestamp": datetime.now(UTC).isoformat(),
                "tools": [{"name": "kri-grain-ingest", "version": "1"}],
            },
            "components": components,
        }

        parser = SBOMParser()
        scan, parsed_components = parser.parse_cyclonedx(node_id, cyclonedx)

        db.add(scan)
        db.flush()
        if parsed_components:
            db.bulk_insert_mappings(
                SBOMComponent,
                [{"scan_id": scan.id, "node_id": node_uuid, **c} for c in parsed_components],
            )
        db.commit()
        scan_id = scan.id

    archive_old_scans.delay(node_id=node_id, keep_count=3)
    return {"status": "indexed", "node_id": node_id, "component_count": len(parsed_components)}


@celery_app.task(
    name="fleet_platform.workers.sbom_tasks.archive_old_scans",
    bind=True,
    max_retries=3,
    queue="sbom",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
)
def archive_old_scans(self, node_id: str, keep_count: int = 3) -> dict:
    node_uuid = _uuid.UUID(node_id)
    with get_sync_db() as db:
        keep_ids = db.execute(
            select(SBOMScan.id)
            .where(SBOMScan.node_id == node_uuid)
            .order_by(SBOMScan.scanned_at.desc())
            .limit(keep_count)
        ).scalars().all()

        if not keep_ids:
            return {"deleted": 0}

        result = db.execute(
            delete(SBOMScan)
            .where(SBOMScan.node_id == node_uuid)
            .where(SBOMScan.id.not_in(keep_ids))
        )
        db.commit()
    return {"deleted": result.rowcount}


@celery_app.task(
    name="fleet_platform.workers.sbom_tasks.cleanup_old_sbom_scans",
    queue="sbom",
)
def cleanup_old_sbom_scans(keep_count: int = 3) -> dict:
    """Delete old SBOM scans fleet-wide, keeping the last keep_count per node. Run via beat."""
    with get_sync_db() as db:
        result = db.execute(
            text("""
                DELETE FROM sbom_scans
                WHERE id IN (
                    SELECT id FROM (
                        SELECT id,
                               ROW_NUMBER() OVER (
                                   PARTITION BY node_id
                                   ORDER BY scanned_at DESC
                               ) AS rn
                        FROM sbom_scans
                    ) ranked
                    WHERE rn > :keep_count
                )
            """),
            {"keep_count": keep_count},
        )
        db.commit()
    return {"deleted": result.rowcount}
