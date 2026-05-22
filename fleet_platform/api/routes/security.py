# fleet_platform/api/routes/security.py
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.api.deps import get_db
from fleet_platform.core.auth import get_current_user, require_role
from fleet_platform.models.node import Node
from fleet_platform.models.sbom import SBOMScan
from fleet_platform.models.security import LicenseFinding, VulnerabilityFinding

router = APIRouter(prefix="/api/v1/security")


@router.get("/dashboard")
async def security_dashboard(
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    """Fleet-wide security summary."""
    # Vulnerability counts by severity
    vuln_counts = {}
    for sev in ("CRITICAL", "HIGH", "MEDIUM", "LOW"):
        result = await db.execute(
            select(func.count()).select_from(VulnerabilityFinding)
            .where(VulnerabilityFinding.severity == sev)
        )
        vuln_counts[sev.lower()] = result.scalar_one()

    # License risk counts
    lic_counts = {}
    for risk in ("high", "medium", "unknown"):
        result = await db.execute(
            select(func.count()).select_from(LicenseFinding)
            .where(LicenseFinding.risk == risk)
        )
        lic_counts[risk] = result.scalar_one()

    # Nodes with critical/high vulnerabilities
    critical_nodes = await db.execute(
        select(VulnerabilityFinding.node_id)
        .where(VulnerabilityFinding.severity.in_(["CRITICAL", "HIGH"]))
        .distinct()
    )
    critical_node_count = len(critical_nodes.scalars().all())

    # Last scan time
    last_scan = await db.execute(
        select(func.max(VulnerabilityFinding.scanned_at))
    )
    last_scan_at = last_scan.scalar_one()

    return {
        "vulnerabilities": vuln_counts,
        "total_vulnerabilities": sum(vuln_counts.values()),
        "license_risks": lic_counts,
        "nodes_with_critical_or_high": critical_node_count,
        "last_scan_at": last_scan_at,
    }


@router.get("/nodes")
async def security_node_list(
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    """Per-node vulnerability and license summary."""
    # Get all nodes that have SBOM scans
    result = await db.execute(select(Node))
    nodes = result.scalars().all()

    items = []
    for node in nodes:
        # Vuln counts
        vcounts = {}
        for sev in ("CRITICAL", "HIGH", "MEDIUM", "LOW"):
            r = await db.execute(
                select(func.count()).select_from(VulnerabilityFinding)
                .where(VulnerabilityFinding.node_id == node.id)
                .where(VulnerabilityFinding.severity == sev)
            )
            vcounts[sev.lower()] = r.scalar_one()

        # License risk counts
        lcounts = {}
        for risk in ("high", "medium", "unknown"):
            r = await db.execute(
                select(func.count()).select_from(LicenseFinding)
                .where(LicenseFinding.node_id == node.id)
                .where(LicenseFinding.risk == risk)
            )
            lcounts[risk] = r.scalar_one()

        # Last scan
        r = await db.execute(
            select(func.max(VulnerabilityFinding.scanned_at))
            .where(VulnerabilityFinding.node_id == node.id)
        )
        last_scan = r.scalar_one()

        # Has SBOM?
        has_sbom = await db.execute(
            select(func.count()).select_from(SBOMScan)
            .where(SBOMScan.node_id == node.id)
        )
        has_sbom_val = (has_sbom.scalar_one() or 0) > 0

        items.append({
            "node_id": str(node.id),
            "minion_id": node.minion_id,
            "hostname": node.hostname,
            "status": node.status,
            "has_sbom": has_sbom_val,
            "vulnerabilities": vcounts,
            "license_risks": lcounts,
            "last_scanned_at": last_scan,
            "risk_level": (
                "critical" if vcounts.get("critical", 0) > 0
                else "high" if vcounts.get("high", 0) > 0
                else "medium" if (vcounts.get("medium", 0) > 0 or lcounts.get("high", 0) > 0)
                else "low" if vcounts.get("low", 0) > 0
                else "clean" if last_scan else "unscanned"
            ),
        })

    return {"items": items, "total": len(items)}


@router.get("/nodes/{node_id}")
async def security_node_detail(
    node_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    """Detailed vulnerability and license findings for one node."""
    # Vulnerabilities
    result = await db.execute(
        select(VulnerabilityFinding)
        .where(VulnerabilityFinding.node_id == node_id)
        .order_by(
            VulnerabilityFinding.severity.in_(["CRITICAL", "HIGH"]).desc(),
            VulnerabilityFinding.scanned_at.desc()
        )
    )
    vulns = result.scalars().all()

    # License findings
    result = await db.execute(
        select(LicenseFinding)
        .where(LicenseFinding.node_id == node_id)
        .order_by(LicenseFinding.risk.desc(), LicenseFinding.package_name)
    )
    licenses = result.scalars().all()

    return {
        "node_id": str(node_id),
        "vulnerabilities": [
            {
                "id": str(v.id), "cve_id": v.cve_id, "package_name": v.package_name,
                "package_version": v.package_version, "severity": v.severity,
                "cvss_score": v.cvss_score, "fixed_version": v.fixed_version,
                "description": v.description, "reference_url": v.reference_url,
                "scanner": v.scanner, "scanned_at": v.scanned_at,
            }
            for v in vulns
        ],
        "license_findings": [
            {
                "id": str(l.id), "package_name": l.package_name,
                "package_version": l.package_version, "license_id": l.license_id,
                "risk": l.risk, "scanner": l.scanner, "scanned_at": l.scanned_at,
            }
            for l in licenses
        ],
    }


_VALID_SCANNERS = {"trivy", "cxone", "sonarqube"}


@router.post("/scan/{node_id}", status_code=202)
async def trigger_node_scan(
    node_id: uuid.UUID,
    scanner: str = "trivy",
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("operator", "admin")),
):
    """Trigger a vulnerability/license scan for a specific node."""
    if scanner not in _VALID_SCANNERS:
        raise HTTPException(status_code=422, detail=f"Invalid scanner '{scanner}'. Must be one of: {sorted(_VALID_SCANNERS)}")
    from fleet_platform.workers.security_tasks import scan_node_security
    result = await db.execute(select(Node).where(Node.id == node_id))
    node = result.scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")

    task = scan_node_security.delay(str(node_id), scanner=scanner)
    return {"task_id": task.id, "node_id": str(node_id), "scanner": scanner, "status": "queued"}


@router.post("/scan-all", status_code=202)
async def trigger_fleet_scan(
    scanner: str = "trivy",
    _: dict = Depends(require_role("operator", "admin")),
):
    """Trigger vulnerability/license scans for all nodes."""
    if scanner not in _VALID_SCANNERS:
        raise HTTPException(status_code=422, detail=f"Invalid scanner '{scanner}'. Must be one of: {sorted(_VALID_SCANNERS)}")
    from fleet_platform.workers.security_tasks import scan_all_nodes
    task = scan_all_nodes.delay(scanner=scanner)
    return {"task_id": task.id, "scanner": scanner, "status": "queued"}


@router.get("/integration-status")
async def integration_status(
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    """Check connectivity to external security tools."""
    import subprocess
    import urllib.request
    from fleet_platform.services.platform_settings_svc import (
        CXONE_URL, SONARQUBE_URL, get_setting,
    )

    # Trivy
    try:
        trivy_ok = subprocess.run(["trivy", "--version"], capture_output=True, timeout=5).returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        trivy_ok = False

    # CxOne
    cxone_url = await get_setting(db, CXONE_URL)
    cxone_ok = False
    if cxone_url:
        try:
            urllib.request.urlopen(f"{cxone_url}/api/health", timeout=5)
            cxone_ok = True
        except Exception:
            pass

    # SonarQube
    sonar_url = await get_setting(db, SONARQUBE_URL)
    sonar_ok = False
    if sonar_url:
        try:
            urllib.request.urlopen(f"{sonar_url}/api/system/health", timeout=5)
            sonar_ok = True
        except Exception:
            pass

    return {
        "trivy": {"available": trivy_ok, "configured": True},
        "cxone": {"available": cxone_ok, "configured": bool(cxone_url)},
        "sonarqube": {"available": sonar_ok, "configured": bool(sonar_url)},
    }
