"""Celery tasks for vulnerability and license scanning."""

import json
import subprocess
import tempfile
import uuid as _uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import delete, select

from fleet_platform.db.session import get_sync_db
from fleet_platform.models.sbom import SBOMComponent, SBOMScan
from fleet_platform.models.security import LicenseFinding, VulnerabilityFinding
from fleet_platform.workers.celery_app import celery_app

# License risk classification
_HIGH_RISK_LICENSES = {
    "GPL-1.0",
    "GPL-2.0",
    "GPL-3.0",
    "GPL-2.0-only",
    "GPL-3.0-only",
    "AGPL-1.0",
    "AGPL-3.0",
    "AGPL-3.0-only",
    "SSPL-1.0",
}
_MEDIUM_RISK_LICENSES = {
    "LGPL-2.0",
    "LGPL-2.1",
    "LGPL-3.0",
    "LGPL-2.0-only",
    "LGPL-2.1-only",
    "LGPL-3.0-only",
    "MPL-2.0",
    "EUPL-1.2",
    "CDDL-1.0",
}
_ALLOWED_LICENSES = {
    "MIT",
    "Apache-2.0",
    "BSD-2-Clause",
    "BSD-3-Clause",
    "ISC",
    "0BSD",
    "CC0-1.0",
    "Unlicense",
    "Zlib",
    "PSF-2.0",
}


def _classify_license(spdx_id: str) -> str:
    upper = spdx_id.upper().replace(" ", "-")
    for lic in _HIGH_RISK_LICENSES:
        if lic.upper() in upper:
            return "high"
    for lic in _MEDIUM_RISK_LICENSES:
        if lic.upper() in upper:
            return "medium"
    for lic in _ALLOWED_LICENSES:
        if lic.upper() in upper:
            return "allowed"
    return "unknown"


def _build_cyclonedx(node_id: str, components: list) -> dict:
    """Build a minimal CycloneDX JSON from SBOM components for Trivy input."""
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.4",
        "metadata": {
            "timestamp": datetime.now(UTC).isoformat(),
            "component": {"name": f"kri-node-{node_id}", "version": "0", "type": "container"},
        },
        "components": [
            {
                "type": comp.component_type or "library",
                "name": comp.name,
                "version": comp.version or "",
                "purl": comp.purl or f"pkg:generic/{comp.name}@{comp.version or 'unknown'}",
                "licenses": [{"expression": lic} for lic in (comp.licenses or [])],
                "cpes": comp.cpes or [],
            }
            for comp in components
        ],
    }


def _run_trivy(sbom_path: str) -> tuple[list[dict], list[dict]]:
    """Run trivy sbom for vuln + license. Returns (vulns, licenses)."""
    vulns, licenses = [], []

    # Vulnerability scan
    try:
        result = subprocess.run(
            ["trivy", "sbom", "--scanners", "vuln", "--format", "json", "--quiet", sbom_path],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode == 0 and result.stdout:
            data = json.loads(result.stdout)
            for result_item in data.get("Results", []):
                for vuln in result_item.get("Vulnerabilities", []):
                    vulns.append(
                        {
                            "cve_id": vuln.get("VulnerabilityID", ""),
                            "package_name": vuln.get("PkgName", ""),
                            "package_version": vuln.get("InstalledVersion"),
                            "severity": vuln.get("Severity", "UNKNOWN"),
                            "cvss_score": (vuln.get("CVSS", {}).get("nvd", {}) or {}).get("V3Score"),
                            "fixed_version": vuln.get("FixedVersion"),
                            "description": (vuln.get("Description") or "")[:500],
                            "reference_url": (vuln.get("References") or [""])[0],
                        }
                    )
    except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError):
        pass

    # License scan
    try:
        result = subprocess.run(
            ["trivy", "sbom", "--scanners", "license", "--format", "json", "--quiet", sbom_path],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode == 0 and result.stdout:
            data = json.loads(result.stdout)
            for result_item in data.get("Results", []):
                for lic in result_item.get("Licenses", []):
                    for spdx in lic.get("Findings") or []:
                        license_id = spdx.get("Name", "")
                        if license_id:
                            licenses.append(
                                {
                                    "package_name": lic.get("PkgName", ""),
                                    "package_version": lic.get("PkgVersion"),
                                    "license_id": license_id,
                                    "risk": _classify_license(license_id),
                                }
                            )
    except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError):
        pass

    return vulns, licenses


@celery_app.task(
    name="fleet_platform.workers.security_tasks.scan_node_security",
    bind=True,
    max_retries=2,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    queue="default",
)
def scan_node_security(self, node_id: str, scanner: str = "trivy") -> dict:
    """Scan a node's SBOM for vulnerabilities and license issues."""
    node_uuid = _uuid.UUID(node_id)
    now = datetime.now(UTC)

    with get_sync_db() as db:
        # Get latest SBOM for the node
        scan = db.execute(
            select(SBOMScan).where(SBOMScan.node_id == node_uuid).order_by(SBOMScan.scanned_at.desc()).limit(1)
        ).scalar_one_or_none()

        if not scan:
            return {"status": "no_sbom", "node_id": node_id}

        components = db.execute(select(SBOMComponent).where(SBOMComponent.scan_id == scan.id)).scalars().all()

        if not components:
            return {"status": "no_components", "node_id": node_id}

        cyclonedx = _build_cyclonedx(node_id, list(components))

    vuln_rows: list[VulnerabilityFinding] = []
    license_rows: list[LicenseFinding] = []

    if scanner == "trivy":
        with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as f:
            json.dump(cyclonedx, f)
            sbom_path = f.name
        try:
            vulns, licenses = _run_trivy(sbom_path)
        finally:
            Path(sbom_path).unlink(missing_ok=True)

        for v in vulns:
            vuln_rows.append(
                VulnerabilityFinding(
                    node_id=node_uuid,
                    scanner="trivy",
                    scanned_at=now,
                    **v,
                )
            )
        for lic in licenses:
            license_rows.append(
                LicenseFinding(
                    node_id=node_uuid,
                    scanner="trivy",
                    scanned_at=now,
                    **lic,
                )
            )

    elif scanner == "cxone":
        vuln_rows, license_rows = _scan_cxone(node_uuid, cyclonedx, now)

    # Wipe previous findings from this scanner for this node, then insert fresh
    with get_sync_db() as db:
        db.execute(
            delete(VulnerabilityFinding)
            .where(VulnerabilityFinding.node_id == node_uuid)
            .where(VulnerabilityFinding.scanner == scanner)
        )
        db.execute(
            delete(LicenseFinding).where(LicenseFinding.node_id == node_uuid).where(LicenseFinding.scanner == scanner)
        )
        for vrow in vuln_rows:
            db.add(vrow)
        for lrow in license_rows:
            db.add(lrow)
        db.commit()

    return {
        "status": "ok",
        "node_id": node_id,
        "scanner": scanner,
        "vulnerabilities": len(vuln_rows),
        "license_findings": len(license_rows),
    }


def _scan_cxone(node_uuid: _uuid.UUID, cyclonedx: dict, now: datetime):
    """Submit SBOM to CxOne SCA and retrieve findings."""
    import time as _time
    import urllib.request

    import sqlalchemy as _sa

    from fleet_platform.db.session import get_sync_db as _db
    from fleet_platform.models.platform_setting import PlatformSetting
    from fleet_platform.services.platform_settings_svc import (
        CXONE_API_TOKEN,
        CXONE_URL,
        _fernet,
    )

    cxone_url, token = "", ""
    with _db() as db:
        for key, setting_key in [("url", CXONE_URL), ("tok", CXONE_API_TOKEN)]:
            row = db.execute(_sa.select(PlatformSetting).where(PlatformSetting.key == setting_key)).scalar_one_or_none()
            if row and row.value:
                val = _fernet().decrypt(row.value.encode()).decode() if row.is_encrypted else row.value
                if key == "url":
                    cxone_url = val.rstrip("/")
                else:
                    token = val

    if not cxone_url or not token:
        return [], []

    try:
        sbom_bytes = json.dumps(cyclonedx).encode()
        req = urllib.request.Request(
            f"{cxone_url}/api/sca/risk-management/scans",
            data=sbom_bytes,
            headers={"Content-Type": "application/json", "CX-Auth": f"Bearer {token}"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:  # nosec B310
            scan_resp = json.loads(resp.read())
        scan_id = scan_resp.get("id", "")

        # Poll for completion (max 2.5 min)
        for _ in range(30):
            _time.sleep(5)
            status_req = urllib.request.Request(
                f"{cxone_url}/api/sca/risk-management/scans/{scan_id}",
                headers={"CX-Auth": f"Bearer {token}"},
            )
            with urllib.request.urlopen(status_req, timeout=15) as r:  # nosec B310
                status = json.loads(r.read())
            if status.get("status") in ("Done", "Failed"):
                break

        # Fetch vulnerabilities
        vuln_req = urllib.request.Request(
            f"{cxone_url}/api/sca/risk-management/vulnerabilities?scanId={scan_id}",
            headers={"CX-Auth": f"Bearer {token}"},
        )
        with urllib.request.urlopen(vuln_req, timeout=30) as r:  # nosec B310
            vuln_data = json.loads(r.read())

        vuln_rows = [
            VulnerabilityFinding(
                node_id=node_uuid,
                scanner="cxone",
                cve_id=v.get("id", ""),
                package_name=v.get("packageName", ""),
                package_version=v.get("packageVersion"),
                severity=v.get("severity", "UNKNOWN").upper(),
                cvss_score=v.get("cvssScore"),
                fixed_version=v.get("fixVersion"),
                description=(v.get("description") or "")[:500],
                reference_url=v.get("url"),
                scanned_at=now,
            )
            for v in (vuln_data.get("items") or [])
        ]
        return vuln_rows, []
    except Exception:
        return [], []


@celery_app.task(
    name="fleet_platform.workers.security_tasks.scan_all_nodes",
    queue="default",
)
def scan_all_nodes(scanner: str = "trivy") -> dict:
    """Trigger security scans for all nodes that have SBOM data."""
    import sqlalchemy as _sa

    with get_sync_db() as db:
        node_ids = [str(r[0]) for r in db.execute(_sa.select(SBOMScan.node_id).distinct()).all()]

    for nid in node_ids:
        scan_node_security.delay(nid, scanner=scanner)

    return {"queued": len(node_ids), "scanner": scanner}
