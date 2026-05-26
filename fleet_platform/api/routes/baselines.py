# fleet_platform/api/routes/baselines.py
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.api.deps import get_db
from fleet_platform.core.auth import get_current_user, require_role
from fleet_platform.models.drift import DesiredStateBaseline
from fleet_platform.schemas.common import PaginatedResponse
from fleet_platform.schemas.drift import BaselineCreate, BaselineResponse

router = APIRouter(prefix="/api/v1/baselines")


@router.get("/capture/{node_id}")
async def capture_node_state(
    node_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("operator", "admin")),
):
    """Return the latest grain facts for a node, formatted for baseline capture."""
    from fleet_platform.models.facts import NodeFact
    result = await db.execute(
        select(NodeFact)
        .where(NodeFact.node_id == node_id)
        .order_by(NodeFact.collected_at.desc())
        .limit(1)
    )
    fact = result.scalar_one_or_none()
    if not fact:
        raise HTTPException(status_code=404, detail="No grain facts found for this node — bootstrap it first")

    grains = fact.grains
    pkgs: dict[str, str] = {}
    for key in ("pkgs", "brew_pkgs", "pip_pkgs"):
        val = grains.get(key)
        if isinstance(val, dict):
            pkgs.update(val)

    packages = [
        {"name": name, "version": str(ver) if ver else None}
        for name, ver in sorted(pkgs.items())
    ]

    services = list(grains.get("services") or [])

    from fleet_platform.models.node import Node
    node_result = await db.execute(select(Node).where(Node.id == node_id))
    node = node_result.scalar_one_or_none()

    return {
        "node_id": str(node_id),
        "hostname": node.hostname if node else None,
        "minion_id": node.minion_id if node else str(node_id),
        "package_count": len(packages),
        "packages": packages,
        "services": services,
        "collected_at": fact.collected_at.isoformat() if fact.collected_at else None,
    }


@router.get("/common-packages")
async def common_packages(
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    """Return the most frequently installed packages across all fleet nodes."""
    from sqlalchemy import func as _func

    from fleet_platform.models.sbom import SBOMComponent, SBOMScan

    # Count how many distinct nodes have each package (from latest SBOM per node)
    latest_scans = (
        select(_func.max(SBOMScan.scanned_at).label("max_at"), SBOMScan.node_id)
        .group_by(SBOMScan.node_id)
        .subquery()
    )
    result = await db.execute(
        select(
            SBOMComponent.name,
            SBOMComponent.version,
            _func.count(_func.distinct(SBOMComponent.node_id)).label("node_count"),
        )
        .join(SBOMScan, SBOMComponent.scan_id == SBOMScan.id)
        .join(
            latest_scans,
            (SBOMScan.node_id == latest_scans.c.node_id) &
            (SBOMScan.scanned_at == latest_scans.c.max_at),
        )
        .group_by(SBOMComponent.name, SBOMComponent.version)
        .order_by(_func.count(_func.distinct(SBOMComponent.node_id)).desc())
        .limit(limit)
    )
    rows = result.all()
    return [{"name": r.name, "version": r.version or "", "node_count": r.node_count} for r in rows]


@router.get("", response_model=PaginatedResponse[BaselineResponse])
async def list_baselines(
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=25, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    total = (await db.execute(select(func.count()).select_from(DesiredStateBaseline))).scalar_one()
    result = await db.execute(
        select(DesiredStateBaseline)
        .order_by(DesiredStateBaseline.name)
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    baselines = result.scalars().all()
    return PaginatedResponse(
        items=[BaselineResponse.model_validate(b) for b in baselines],
        total=total, page=page, per_page=per_page,
    )


@router.post("", response_model=BaselineResponse, status_code=201)
async def create_baseline(
    payload: BaselineCreate,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_role("admin")),
):
    from fleet_platform.core.audit import audit
    baseline = DesiredStateBaseline(
        name=payload.name,
        description=payload.description,
        target_type=payload.target_type,
        target_id=payload.target_id,
        git_commit_sha=payload.git_commit_sha,
        state_json=payload.state_json,
    )
    db.add(baseline)
    await db.flush()
    await audit(db, actor=claims["email"], action="baseline.create",
                resource_type="baseline", resource_id=baseline.id,
                new_value={"name": baseline.name, "target_type": baseline.target_type})
    await db.commit()
    await db.refresh(baseline)
    return BaselineResponse.model_validate(baseline)


@router.get("/{baseline_id}", response_model=BaselineResponse)
async def get_baseline(
    baseline_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    result = await db.execute(
        select(DesiredStateBaseline).where(DesiredStateBaseline.id == baseline_id)
    )
    baseline = result.scalar_one_or_none()
    if not baseline:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Baseline not found")
    return BaselineResponse.model_validate(baseline)


@router.patch("/{baseline_id}", response_model=BaselineResponse)
async def update_baseline(
    baseline_id: uuid.UUID,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_role("operator", "admin")),
):
    from fleet_platform.core.audit import audit
    result = await db.execute(
        select(DesiredStateBaseline).where(DesiredStateBaseline.id == baseline_id)
    )
    baseline = result.scalar_one_or_none()
    if not baseline:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Baseline not found")
    if "name" in payload:
        baseline.name = payload["name"]
    if "state_json" in payload:
        baseline.state_json = payload["state_json"]
        baseline.version = baseline.version + 1
    if "description" in payload:
        baseline.description = payload["description"]
    await audit(db, actor=claims["email"], action="baseline.update",
                resource_type="baseline", resource_id=baseline_id,
                new_value={"name": baseline.name})
    await db.commit()
    await db.refresh(baseline)
    return BaselineResponse.model_validate(baseline)
