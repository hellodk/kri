# fleet_platform/api/routes/security.py
import ipaddress
import logging
import urllib.parse
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.api.deps import get_db
from fleet_platform.core.audit import audit
from fleet_platform.core.auth import require_role
from fleet_platform.models.node import Node
from fleet_platform.models.sbom import SBOMScan
from fleet_platform.models.security import LicenseFinding, VulnerabilityFinding

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/security")

# ---------------------------------------------------------------------------
# SSRF guard for integration-status URL fetches
# ---------------------------------------------------------------------------

_ALLOWED_SCHEMES = {"https", "http"}


def _ssrf_safe_url(url: str) -> None:
    """Raise HTTPException(422) if *url* looks like an SSRF target.

    Checks:
    - Scheme must be http or https.
    - Hostname must not resolve to a loopback / link-local / private address
      or the cloud-metadata IP (169.254.169.254).

    Note: this is a best-effort guard on the stored URL value.  It does not
    prevent DNS rebinding (which requires network-level controls), but it
    blocks the most common SSRF patterns.
    """
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception:
        raise HTTPException(status_code=422, detail=f"Malformed URL: {url!r}")

    scheme = (parsed.scheme or "").lower()
    if scheme not in _ALLOWED_SCHEMES:
        raise HTTPException(
            status_code=422,
            detail=f"URL scheme {scheme!r} is not allowed. Only http/https are permitted.",
        )

    hostname = parsed.hostname or ""
    if not hostname:
        raise HTTPException(status_code=422, detail="URL has no hostname.")

    # Reject numeric IPs that are loopback / link-local / private / metadata
    try:
        addr = ipaddress.ip_address(hostname)
    except ValueError:
        # Not a bare IP — hostname-based; we can't resolve here so allow it.
        # Operators are responsible for not pointing these at internal services.
        return

    _BLOCKED_NETWORKS = [
        ipaddress.ip_network("127.0.0.0/8"),  # loopback
        ipaddress.ip_network("::1/128"),  # IPv6 loopback
        ipaddress.ip_network("10.0.0.0/8"),  # RFC-1918 private
        ipaddress.ip_network("172.16.0.0/12"),  # RFC-1918 private
        ipaddress.ip_network("192.168.0.0/16"),  # RFC-1918 private
        ipaddress.ip_network("169.254.0.0/16"),  # link-local / AWS metadata
        ipaddress.ip_network("fc00::/7"),  # IPv6 ULA
        ipaddress.ip_network("fe80::/10"),  # IPv6 link-local
    ]
    for net in _BLOCKED_NETWORKS:
        if addr in net:
            raise HTTPException(
                status_code=422,
                detail=f"URL target {hostname!r} resolves to a blocked/internal address range.",
            )


@router.get("/dashboard")
async def security_dashboard(
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("operator", "admin", "auditor")),
):
    """Fleet-wide security summary."""
    # Vulnerability counts by severity
    vuln_counts = {}
    for sev in ("CRITICAL", "HIGH", "MEDIUM", "LOW"):
        result = await db.execute(
            select(func.count()).select_from(VulnerabilityFinding).where(VulnerabilityFinding.severity == sev)
        )
        vuln_counts[sev.lower()] = result.scalar_one()

    # License risk counts
    lic_counts = {}
    for risk in ("high", "medium", "unknown"):
        result = await db.execute(select(func.count()).select_from(LicenseFinding).where(LicenseFinding.risk == risk))
        lic_counts[risk] = result.scalar_one()

    # Nodes with critical/high vulnerabilities
    critical_nodes = await db.execute(
        select(VulnerabilityFinding.node_id).where(VulnerabilityFinding.severity.in_(["CRITICAL", "HIGH"])).distinct()
    )
    critical_node_count = len(critical_nodes.scalars().all())

    # Last scan time
    last_scan = await db.execute(select(func.max(VulnerabilityFinding.scanned_at)))
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
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("operator", "admin", "auditor")),
):
    """Per-node vulnerability and license summary.

    Uses 5 aggregate queries instead of 9 per-node queries (N+1 fix).
    """
    # Count total nodes for pagination metadata
    total = (await db.execute(select(func.count()).select_from(Node))).scalar_one()

    # Fetch paginated nodes
    node_query = select(Node).offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(node_query)
    nodes = result.scalars().all()

    # --- Aggregate query 1: vuln counts grouped by node_id + severity ---
    vuln_rows = await db.execute(
        select(
            VulnerabilityFinding.node_id,
            VulnerabilityFinding.severity,
            func.count().label("cnt"),
        ).group_by(VulnerabilityFinding.node_id, VulnerabilityFinding.severity)
    )
    vuln_map: dict[str, dict[str, int]] = {}
    for row in vuln_rows:
        vuln_map.setdefault(str(row.node_id), {})[row.severity.lower()] = row.cnt

    # --- Aggregate query 2: license risk counts grouped by node_id + risk ---
    lic_rows = await db.execute(
        select(
            LicenseFinding.node_id,
            LicenseFinding.risk,
            func.count().label("cnt"),
        ).group_by(LicenseFinding.node_id, LicenseFinding.risk)
    )
    lic_map: dict[str, dict[str, int]] = {}
    for row in lic_rows:
        lic_map.setdefault(str(row.node_id), {})[row.risk] = row.cnt

    # --- Aggregate query 3: last scan time per node ---
    scan_rows = await db.execute(
        select(
            VulnerabilityFinding.node_id,
            func.max(VulnerabilityFinding.scanned_at).label("last_scan"),
        ).group_by(VulnerabilityFinding.node_id)
    )
    scan_map: dict[str, object] = {str(row.node_id): row.last_scan for row in scan_rows}

    # --- Aggregate query 4: which nodes have at least one SBOM scan ---
    sbom_rows = await db.execute(select(SBOMScan.node_id).distinct())
    sbom_set: set[str] = {str(r.node_id) for r in sbom_rows}

    # Build response without any per-node queries
    items = []
    for node in nodes:
        nid = str(node.id)
        vcounts = vuln_map.get(nid, {})
        lcounts = lic_map.get(nid, {})
        last_scan = scan_map.get(nid)
        has_sbom_val = nid in sbom_set

        items.append(
            {
                "node_id": nid,
                "minion_id": node.minion_id,
                "hostname": node.hostname,
                "status": node.status,
                "has_sbom": has_sbom_val,
                "vulnerabilities": {
                    "critical": vcounts.get("critical", 0),
                    "high": vcounts.get("high", 0),
                    "medium": vcounts.get("medium", 0),
                    "low": vcounts.get("low", 0),
                },
                "license_risks": {
                    "high": lcounts.get("high", 0),
                    "medium": lcounts.get("medium", 0),
                    "unknown": lcounts.get("unknown", 0),
                },
                "last_scanned_at": last_scan,
                "risk_level": (
                    "critical"
                    if vcounts.get("critical", 0) > 0
                    else "high"
                    if vcounts.get("high", 0) > 0
                    else "medium"
                    if (vcounts.get("medium", 0) > 0 or lcounts.get("high", 0) > 0)
                    else "low"
                    if vcounts.get("low", 0) > 0
                    else "clean"
                    if last_scan
                    else "unscanned"
                ),
            }
        )

    return {"items": items, "total": total, "page": page, "per_page": per_page}


@router.get("/nodes/{node_id}")
async def security_node_detail(
    node_id: uuid.UUID,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("operator", "admin", "auditor")),
):
    """Detailed vulnerability and license findings for one node."""
    # Vulnerabilities
    vuln_query = (
        select(VulnerabilityFinding)
        .where(VulnerabilityFinding.node_id == node_id)
        .order_by(
            VulnerabilityFinding.severity.in_(["CRITICAL", "HIGH"]).desc(), VulnerabilityFinding.scanned_at.desc()
        )
    )
    total_vulns = (await db.execute(select(func.count()).select_from(vuln_query.subquery()))).scalar_one()
    result = await db.execute(vuln_query.offset((page - 1) * per_page).limit(per_page))
    vulns = result.scalars().all()

    # License findings
    lic_query = (
        select(LicenseFinding)
        .where(LicenseFinding.node_id == node_id)
        .order_by(LicenseFinding.risk.desc(), LicenseFinding.package_name)
    )
    total_licenses = (await db.execute(select(func.count()).select_from(lic_query.subquery()))).scalar_one()
    lic_result = await db.execute(lic_query.offset((page - 1) * per_page).limit(per_page))
    licenses = lic_result.scalars().all()

    return {
        "node_id": str(node_id),
        "page": page,
        "per_page": per_page,
        "total_vulnerabilities": total_vulns,
        "total_license_findings": total_licenses,
        "vulnerabilities": [
            {
                "id": str(v.id),
                "cve_id": v.cve_id,
                "package_name": v.package_name,
                "package_version": v.package_version,
                "severity": v.severity,
                "cvss_score": v.cvss_score,
                "fixed_version": v.fixed_version,
                "description": v.description,
                "reference_url": v.reference_url,
                "scanner": v.scanner,
                "scanned_at": v.scanned_at,
            }
            for v in vulns
        ],
        "license_findings": [
            {
                "id": str(lic.id),
                "package_name": lic.package_name,
                "package_version": lic.package_version,
                "license_id": lic.license_id,
                "risk": lic.risk,
                "scanner": lic.scanner,
                "scanned_at": lic.scanned_at,
            }
            for lic in licenses
        ],
    }


_VALID_SCANNERS = {"trivy", "cxone", "sonarqube"}


@router.post("/scan/{node_id}", status_code=202)
async def trigger_node_scan(
    node_id: uuid.UUID,
    scanner: str = "trivy",
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_role("operator", "admin")),
):
    """Trigger a vulnerability/license scan for a specific node."""
    if scanner not in _VALID_SCANNERS:
        raise HTTPException(
            status_code=422, detail=f"Invalid scanner '{scanner}'. Must be one of: {sorted(_VALID_SCANNERS)}"
        )  # noqa: E501
    from fleet_platform.workers.security_tasks import scan_node_security

    result = await db.execute(select(Node).where(Node.id == node_id))
    node = result.scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")

    task = scan_node_security.delay(str(node_id), scanner=scanner)
    await audit(
        db,
        actor=claims["email"],
        action="security_scan.trigger",
        resource_type="node",
        resource_id=node_id,
        new_value={"scanner": scanner, "task_id": task.id},
    )
    await db.commit()
    return {"task_id": task.id, "node_id": str(node_id), "scanner": scanner, "status": "queued"}


@router.post("/scan-all", status_code=202)
async def trigger_fleet_scan(
    scanner: str = "trivy",
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_role("operator", "admin")),
):
    """Trigger vulnerability/license scans for all nodes."""
    if scanner not in _VALID_SCANNERS:
        raise HTTPException(
            status_code=422, detail=f"Invalid scanner '{scanner}'. Must be one of: {sorted(_VALID_SCANNERS)}"
        )  # noqa: E501
    from fleet_platform.workers.security_tasks import scan_all_nodes

    task = scan_all_nodes.delay(scanner=scanner)
    await audit(
        db,
        actor=claims["email"],
        action="security_scan.trigger_fleet",
        resource_type="fleet",
        new_value={"scanner": scanner, "task_id": task.id},
    )
    await db.commit()
    return {"task_id": task.id, "scanner": scanner, "status": "queued"}


@router.get("/integration-status")
async def integration_status(
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("operator", "admin", "auditor")),
):
    """Check connectivity to external security tools."""
    import asyncio
    import subprocess
    import urllib.request

    from fleet_platform.services.platform_settings_svc import (
        CXONE_URL,
        SONARQUBE_URL,
        get_setting,
    )

    # Trivy — use asyncio.to_thread to avoid blocking the event loop
    try:
        result = await asyncio.to_thread(subprocess.run, ["trivy", "--version"], capture_output=True, timeout=5)
        trivy_ok = result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        trivy_ok = False

    # CxOne — use asyncio.to_thread to avoid blocking the event loop
    cxone_url = await get_setting(db, CXONE_URL)
    cxone_ok = False
    if cxone_url:
        _ssrf_safe_url(cxone_url)
        try:
            await asyncio.to_thread(
                urllib.request.urlopen,
                f"{cxone_url}/api/health",
                timeout=5,  # nosec B310
            )
            cxone_ok = True
        except Exception:
            pass

    # SonarQube — use asyncio.to_thread to avoid blocking the event loop
    sonar_url = await get_setting(db, SONARQUBE_URL)
    sonar_ok = False
    if sonar_url:
        _ssrf_safe_url(sonar_url)
        try:
            await asyncio.to_thread(
                urllib.request.urlopen,
                f"{sonar_url}/api/system/health",
                timeout=5,  # nosec B310
            )
            sonar_ok = True
        except Exception:
            pass

    return {
        "trivy": {"available": trivy_ok, "configured": True},
        "cxone": {"available": cxone_ok, "configured": bool(cxone_url)},
        "sonarqube": {"available": sonar_ok, "configured": bool(sonar_url)},
    }
