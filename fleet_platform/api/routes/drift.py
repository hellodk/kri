# fleet_platform/api/routes/drift.py
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.api.deps import get_db
from fleet_platform.core.auth import get_current_user, require_role
from fleet_platform.models.drift import DesiredStateBaseline, DriftRecord
from fleet_platform.models.node import Node
from fleet_platform.schemas.common import PaginatedResponse
from fleet_platform.schemas.drift import (
    DriftRecordResponse,
    DriftSummaryResponse,
    drift_severity,
)
from fleet_platform.workers.celery_app import celery_app

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _pkg_name(pkg: dict) -> str:
    """Normalise package dict to a name string."""
    return pkg.get("name") or pkg.get("package") or pkg.get("pkg") or ""


router = APIRouter(prefix="/api/v1/drift")

_SEVERITY_RANGES = {
    "clean": (0, 5),
    "low": (6, 20),
    "medium": (21, 50),
    "high": (51, 80),
    "critical": (81, 100),
}


@router.get("", response_model=PaginatedResponse[DriftSummaryResponse])
async def list_drift(
    severity: str | None = None,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=25, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    """List all nodes ordered by drift_score descending."""
    query = select(Node)

    if severity:
        if severity not in _SEVERITY_RANGES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"severity must be one of {list(_SEVERITY_RANGES)}",
            )
        lo, hi = _SEVERITY_RANGES[severity]
        query = query.where(Node.drift_score >= lo, Node.drift_score <= hi)

    query = query.order_by(Node.drift_score.desc())
    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar_one()
    result = await db.execute(query.offset((page - 1) * per_page).limit(per_page))
    nodes = result.scalars().all()

    # Single query: fetch the latest DriftRecord per node in one round-trip
    # using a subquery that selects the max computed_at per node_id.
    node_ids = [n.id for n in nodes]
    latest_dr_map: dict[uuid.UUID, tuple] = {}  # node_id → (computed_at, baseline_name)
    if node_ids:
        # Subquery: max computed_at per node_id
        latest_subq = (
            select(
                DriftRecord.node_id,
                func.max(DriftRecord.computed_at).label("max_computed_at"),
            )
            .where(DriftRecord.node_id.in_(node_ids))
            .group_by(DriftRecord.node_id)
            .subquery()
        )
        dr_result = await db.execute(
            select(DriftRecord, DesiredStateBaseline)
            .outerjoin(DesiredStateBaseline, DesiredStateBaseline.id == DriftRecord.baseline_id)
            .join(
                latest_subq,
                (DriftRecord.node_id == latest_subq.c.node_id)
                & (DriftRecord.computed_at == latest_subq.c.max_computed_at),
            )
        )
        for dr, baseline in dr_result:
            latest_dr_map[dr.node_id] = (dr.computed_at, baseline.name if baseline else None)

    items = []
    for node in nodes:
        computed_at, baseline_name = latest_dr_map.get(node.id, (None, None))
        items.append(
            DriftSummaryResponse(
                node_id=node.id,
                hostname=node.hostname,
                drift_score=node.drift_score,
                severity=drift_severity(node.drift_score),
                computed_at=computed_at,
                baseline_name=baseline_name,
            )
        )

    return PaginatedResponse(items=items, total=total, page=page, per_page=per_page)


@router.get("/compare")
async def compare_drift(
    node_ids: str = Query(..., description="Comma-separated list of node UUIDs"),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    """Compare drift across 2+ nodes side-by-side.

    Returns a matrix of package states keyed by node ID so the frontend can
    render a comparison table without further API calls.
    """
    raw_ids = [s.strip() for s in node_ids.split(",") if s.strip()]
    if len(raw_ids) < 1:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Provide at least one node_id",
        )
    # Validate & de-dup
    parsed_ids: list[uuid.UUID] = []
    for raw in raw_ids:
        try:
            parsed_ids.append(uuid.UUID(raw))
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid UUID: {raw}",
            )
    seen: set[uuid.UUID] = set()
    unique_ids = [i for i in parsed_ids if not (i in seen or seen.add(i))]  # type: ignore[func-returns-value]

    # Fetch nodes
    nodes_result = await db.execute(select(Node).where(Node.id.in_(unique_ids)))
    nodes = {n.id: n for n in nodes_result.scalars().all()}

    # Fetch latest drift record + baseline for each node
    node_data: dict[uuid.UUID, tuple[DriftRecord | None, DesiredStateBaseline | None]] = {}
    for nid in unique_ids:
        dr_result = await db.execute(
            select(DriftRecord, DesiredStateBaseline)
            .outerjoin(DesiredStateBaseline, DesiredStateBaseline.id == DriftRecord.baseline_id)
            .where(DriftRecord.node_id == nid)
            .order_by(DriftRecord.computed_at.desc())
            .limit(1)
        )
        row = dr_result.first()
        node_data[nid] = (row[0] if row else None, row[1] if row else None)

    # Build the union of all package names across all nodes
    # For each node we need: required (from baseline), installed (from drift lists)
    # A package is "ok" if installed == expected, "mismatch" if diff version, "missing" if absent,
    # "extra" if present but not in baseline, None if neither baseline nor drift knows about it.

    def _baseline_pkgs(baseline: DesiredStateBaseline | None) -> dict[str, str | None]:
        """Return {name: expected_version} from the baseline's state_json."""
        if not baseline:
            return {}
        state = baseline.state_json or {}
        pkgs = state.get("packages", {})
        # state_json.packages may be a list [{name, version}] or a dict {required: [...]}
        if isinstance(pkgs, dict):
            required = pkgs.get("required", [])
        elif isinstance(pkgs, list):
            required = pkgs
        else:
            required = []
        return {_pkg_name(p): p.get("version") or p.get("required_version") for p in required if _pkg_name(p)}

    def _installed_pkgs(dr: DriftRecord | None) -> dict[str, str | None]:
        """Build {name: installed_version} from the extra_packages list (everything installed)."""
        if not dr:
            return {}
        installed: dict[str, str | None] = {}
        # extra_packages contains packages that ARE installed
        for p in dr.extra_packages or []:
            name = _pkg_name(p)
            if name:
                installed[name] = p.get("installed_version") or p.get("version")
        # version_mismatches also have an installed version (actual)
        for p in dr.version_mismatches or []:
            name = _pkg_name(p)
            if name and name not in installed:
                installed[name] = p.get("actual") or p.get("installed_version")
        # packages NOT in missing_packages and NOT in extra_packages ARE installed at expected version
        for p in dr.missing_packages or []:
            name = _pkg_name(p)
            if name:
                installed.pop(name, None)  # definitely not installed
        return installed

    # Gather all package names
    all_pkg_names: set[str] = set()
    for nid in unique_ids:
        dr, baseline = node_data[nid]
        all_pkg_names.update(_baseline_pkgs(baseline).keys())
        all_pkg_names.update(_installed_pkgs(dr).keys())
        for p in dr.missing_packages if dr else []:
            name = _pkg_name(p)
            if name:
                all_pkg_names.add(name)
        for p in dr.version_mismatches if dr else []:
            name = _pkg_name(p)
            if name:
                all_pkg_names.add(name)

    # Build the matrix
    packages = []
    drifted_node_ids: set[str] = set()
    for pkg_name in sorted(all_pkg_names):
        states: dict[str, dict] = {}
        for nid in unique_ids:
            dr, baseline = node_data[nid]
            expected_pkgs = _baseline_pkgs(baseline)
            expected_version = expected_pkgs.get(pkg_name)

            # Check explicit missing
            missing_names = {_pkg_name(p) for p in (dr.missing_packages if dr else [])}
            # Check version mismatches
            mismatch_map = {
                _pkg_name(p): (p.get("actual"), p.get("expected") or p.get("required_version"))
                for p in (dr.version_mismatches if dr else [])
                if _pkg_name(p)
            }
            # Check extra (installed but not in baseline)
            extra_map = {
                _pkg_name(p): p.get("installed_version") or p.get("version")
                for p in (dr.extra_packages if dr else [])
                if _pkg_name(p)
            }

            nid_str = str(nid)
            if pkg_name in missing_names:
                states[nid_str] = {
                    "installed": None,
                    "expected": expected_version,
                    "status": "missing",
                }
                drifted_node_ids.add(nid_str)
            elif pkg_name in mismatch_map:
                actual_v, exp_v = mismatch_map[pkg_name]
                states[nid_str] = {
                    "installed": actual_v,
                    "expected": exp_v or expected_version,
                    "status": "mismatch",
                }
                drifted_node_ids.add(nid_str)
            elif pkg_name in extra_map:
                # Extra: installed but not in baseline
                states[nid_str] = {
                    "installed": extra_map[pkg_name],
                    "expected": None,
                    "status": "extra",
                }
            elif expected_version is not None and dr is not None:
                # Package is in baseline, not in missing/mismatch — so it's ok
                states[nid_str] = {
                    "installed": expected_version,
                    "expected": expected_version,
                    "status": "ok",
                }
            else:
                states[nid_str] = {
                    "installed": None,
                    "expected": expected_version,
                    "status": "unknown",
                }

        packages.append({"name": pkg_name, "states": states})

    node_summaries = [
        {
            "id": str(nid),
            "hostname": nodes[nid].hostname if nid in nodes else None,
            "drift_score": nodes[nid].drift_score if nid in nodes else 0,
        }
        for nid in unique_ids
    ]

    return {
        "nodes": node_summaries,
        "packages": packages,
        "summary": {
            "total_packages": len(all_pkg_names),
            "drifted_nodes": len(drifted_node_ids),
        },
    }


@router.get("/{node_id}/latest", response_model=DriftRecordResponse)
async def get_node_drift_latest(
    node_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    """Return the most recent drift record for a node with full diff detail."""
    result = await db.execute(
        select(DriftRecord, DesiredStateBaseline)
        .outerjoin(DesiredStateBaseline, DesiredStateBaseline.id == DriftRecord.baseline_id)
        .where(DriftRecord.node_id == node_id)
        .order_by(DriftRecord.computed_at.desc())
        .limit(1)
    )
    row = result.first()
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No drift records found for this node",
        )

    dr, baseline = row
    return DriftRecordResponse(
        node_id=dr.node_id,
        baseline_id=dr.baseline_id,
        baseline_name=baseline.name if baseline else None,
        computed_at=dr.computed_at,
        drift_score=dr.drift_score,
        severity=drift_severity(dr.drift_score),
        missing_packages=dr.missing_packages,
        extra_packages=dr.extra_packages,
        version_mismatches=dr.version_mismatches,
        service_drift=dr.service_drift,
        config_drift=dr.config_drift,
    )


@router.get("/{node_id}/history", response_model=PaginatedResponse[DriftSummaryResponse])
async def get_node_drift_history(
    node_id: uuid.UUID,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    """Return paginated drift score history for a node (newest first)."""
    total = (await db.execute(select(func.count()).where(DriftRecord.node_id == node_id))).scalar_one()

    result = await db.execute(
        select(DriftRecord)
        .where(DriftRecord.node_id == node_id)
        .order_by(DriftRecord.computed_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    records = result.scalars().all()

    items = [
        DriftSummaryResponse(
            node_id=r.node_id,
            hostname=None,
            drift_score=r.drift_score,
            severity=drift_severity(r.drift_score),
            computed_at=r.computed_at,
            baseline_name=None,
        )
        for r in records
    ]
    return PaginatedResponse(items=items, total=total, page=page, per_page=per_page)


@router.post("/{node_id}/compute", status_code=202)
async def trigger_drift_compute(
    node_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_role("operator", "admin")),
):
    """Enqueue a drift recomputation for a node."""
    from fleet_platform.core.audit import audit

    await audit(db, actor=claims["email"], action="drift.compute.triggered", resource_type="node", resource_id=node_id)
    await db.commit()
    celery_app.send_task("fleet_platform.workers.drift_tasks.compute_drift", args=[str(node_id)], queue="drift")
    return {"status": "queued", "node_id": str(node_id)}
