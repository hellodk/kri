import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.api.deps import get_db
from fleet_platform.core.auth import get_current_user
from fleet_platform.models.node import Node
from fleet_platform.models.sbom import SBOMComponent, SBOMScan
from fleet_platform.schemas.common import PaginatedResponse
from fleet_platform.schemas.sbom import (
    SBOMComponentResponse,
    SBOMDeltaResponse,
    SBOMPackage,
    SBOMScanResponse,
    SBOMSearchResult,
)

router = APIRouter(prefix="/api/v1/sbom")


@router.get("/search", response_model=list[SBOMSearchResult])
async def search_sbom(
    q: str,
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    if len(q.strip()) < 3:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Query must be at least 3 characters",
        )

    # Escape LIKE metacharacters to prevent wildcard injection
    q_safe = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

    latest_scan = (
        select(func.max(SBOMScan.scanned_at).label("max_at"), SBOMScan.node_id)
        .group_by(SBOMScan.node_id)
        .subquery()
    )

    result = await db.execute(
        select(SBOMComponent, SBOMScan, Node)
        .join(SBOMScan, SBOMComponent.scan_id == SBOMScan.id)
        .join(Node, SBOMComponent.node_id == Node.id)
        .join(
            latest_scan,
            and_(
                SBOMScan.node_id == latest_scan.c.node_id,
                SBOMScan.scanned_at == latest_scan.c.max_at,
            ),
        )
        .where(SBOMComponent.name.ilike(f"%{q_safe}%", escape="\\"))
        .order_by(SBOMComponent.name, Node.hostname)
        .limit(limit)
    )
    return [
        SBOMSearchResult(
            name=comp.name,
            version=comp.version,
            purl=comp.purl,
            component_type=comp.component_type,
            hostname=node.hostname,
            node_id=node.id,
            scan_id=scan.id,
            scanned_at=scan.scanned_at,
        )
        for comp, scan, node in result.all()
    ]


@router.get("/browse", response_model=list[SBOMSearchResult])
async def browse_sbom(
    limit: int = Query(default=100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    """Return all packages from the latest SBOM scan per node."""
    latest_scan = (
        select(func.max(SBOMScan.scanned_at).label("max_at"), SBOMScan.node_id)
        .group_by(SBOMScan.node_id)
        .subquery()
    )
    result = await db.execute(
        select(SBOMComponent, SBOMScan, Node)
        .join(SBOMScan, SBOMComponent.scan_id == SBOMScan.id)
        .join(Node, SBOMComponent.node_id == Node.id)
        .join(
            latest_scan,
            and_(
                SBOMScan.node_id == latest_scan.c.node_id,
                SBOMScan.scanned_at == latest_scan.c.max_at,
            ),
        )
        .order_by(SBOMComponent.name.asc())
        .limit(limit)
    )
    rows = result.all()
    return [
        SBOMSearchResult(
            name=r.SBOMComponent.name,
            version=r.SBOMComponent.version,
            purl=r.SBOMComponent.purl,
            component_type=r.SBOMComponent.component_type,
            hostname=r.Node.hostname or r.Node.minion_id,
            node_id=r.Node.id,
            scan_id=r.SBOMScan.id,
            scanned_at=r.SBOMScan.scanned_at,
        )
        for r in rows
    ]


@router.get("/{node_id}/latest", response_model=SBOMScanResponse)
async def get_latest_scan(
    node_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    result = await db.execute(
        select(SBOMScan)
        .where(SBOMScan.node_id == node_id)
        .order_by(SBOMScan.scanned_at.desc())
        .limit(1)
    )
    scan = result.scalar_one_or_none()
    if not scan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No scans found for node")
    return SBOMScanResponse.model_validate(scan)


@router.get("/{node_id}/scans", response_model=PaginatedResponse[SBOMScanResponse])
async def list_scans(
    node_id: uuid.UUID,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=25, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    total = (
        await db.execute(
            select(func.count()).select_from(SBOMScan).where(SBOMScan.node_id == node_id)
        )
    ).scalar_one()
    result = await db.execute(
        select(SBOMScan)
        .where(SBOMScan.node_id == node_id)
        .order_by(SBOMScan.scanned_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    scans = result.scalars().all()
    return PaginatedResponse(
        items=[SBOMScanResponse.model_validate(s) for s in scans],
        total=total,
        page=page,
        per_page=per_page,
    )


@router.get(
    "/{node_id}/scans/{scan_id}/components",
    response_model=PaginatedResponse[SBOMComponentResponse],
)
async def list_scan_components(
    node_id: uuid.UUID,
    scan_id: uuid.UUID,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=100, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    total = (
        await db.execute(
            select(func.count())
            .select_from(SBOMComponent)
            .where(SBOMComponent.scan_id == scan_id)
            .where(SBOMComponent.node_id == node_id)
        )
    ).scalar_one()
    result = await db.execute(
        select(SBOMComponent)
        .where(SBOMComponent.scan_id == scan_id)
        .where(SBOMComponent.node_id == node_id)
        .order_by(SBOMComponent.name)
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    components = result.scalars().all()
    return PaginatedResponse(
        items=[SBOMComponentResponse.model_validate(c) for c in components],
        total=total,
        page=page,
        per_page=per_page,
    )


@router.get("/delta/{node_id}", response_model=SBOMDeltaResponse)
async def sbom_delta(
    node_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
) -> SBOMDeltaResponse:
    """Return packages added/removed between the two most recent SBOM scans for a node."""
    # Get the two most recent scans for this node
    scans_result = await db.execute(
        select(SBOMScan)
        .where(SBOMScan.node_id == node_id)
        .order_by(SBOMScan.scanned_at.desc())
        .limit(2)
    )
    scans = scans_result.scalars().all()

    if len(scans) < 2:
        return SBOMDeltaResponse(
            node_id=str(node_id),
            has_delta=False,
            new_packages=[],
            removed_packages=[],
            new_count=0,
            removed_count=0,
            message="Need at least 2 scans to compute delta",
        )

    latest, previous = scans[0], scans[1]

    # Get package identifiers from each scan (use purl if available, else name+version)
    async def get_package_set(scan_id: uuid.UUID) -> dict[str, dict]:
        result = await db.execute(
            select(SBOMComponent.name, SBOMComponent.version, SBOMComponent.purl).where(
                SBOMComponent.scan_id == scan_id
            )
        )
        packages = {}
        for name, version, purl in result.all():
            key = purl or f"{name}@{version or 'unknown'}"
            packages[key] = {"name": name, "version": version or "", "purl": purl or ""}
        return packages

    latest_pkgs = await get_package_set(latest.id)
    prev_pkgs = await get_package_set(previous.id)

    latest_keys = set(latest_pkgs.keys())
    prev_keys = set(prev_pkgs.keys())

    new_keys = latest_keys - prev_keys
    removed_keys = prev_keys - latest_keys

    return SBOMDeltaResponse(
        node_id=str(node_id),
        has_delta=True,
        latest_scan_at=latest.scanned_at,
        previous_scan_at=previous.scanned_at,
        new_packages=[
            SBOMPackage(**latest_pkgs[k]) for k in sorted(new_keys)
        ],
        removed_packages=[
            SBOMPackage(**prev_pkgs[k]) for k in sorted(removed_keys)
        ],
        new_count=len(new_keys),
        removed_count=len(removed_keys),
    )
