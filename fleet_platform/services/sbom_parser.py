import uuid
from datetime import datetime, timezone

from fleet_platform.models.sbom import SBOMScan


class SBOMParser:
    def parse_cyclonedx(self, node_id: str, raw: dict) -> tuple[SBOMScan, list[dict]]:
        metadata = raw.get("metadata", {})
        tools = metadata.get("tools", [])
        syft_version = next(
            (t.get("version") for t in tools if t.get("name") == "syft"), None
        )

        ts_raw = metadata.get("timestamp", "")
        try:
            scanned_at = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            scanned_at = datetime.now(timezone.utc)

        raw_components = raw.get("components", [])
        components = [self._normalise(c) for c in raw_components]

        scan = SBOMScan(
            node_id=uuid.UUID(node_id),
            syft_version=syft_version,
            format="cyclonedx",
            scanned_at=scanned_at,
            component_count=len(components),
        )
        return scan, components

    def _normalise(self, comp: dict) -> dict:
        licenses = []
        for lic in comp.get("licenses", []):
            expr = lic.get("expression") or (lic.get("license") or {}).get("id") or (lic.get("license") or {}).get("name")
            if expr:
                licenses.append(expr)

        cpe = comp.get("cpe")
        cpes = [cpe] if cpe else []

        return {
            "name": comp.get("name", ""),
            "version": comp.get("version"),
            "purl": comp.get("purl"),
            "component_type": comp.get("type"),
            "licenses": licenses,
            "cpes": cpes,
        }
