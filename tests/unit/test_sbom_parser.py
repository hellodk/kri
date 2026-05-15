import uuid
from datetime import timezone

import pytest

from fleet_platform.services.sbom_parser import SBOMParser

_NODE_ID = str(uuid.uuid4())

_MINIMAL_CYCLONEDX = {
    "bomFormat": "CycloneDX",
    "specVersion": "1.4",
    "metadata": {
        "timestamp": "2026-05-14T12:00:00Z",
        "tools": [{"name": "syft", "version": "1.2.3"}],
    },
    "components": [
        {
            "type": "library",
            "name": "openssl",
            "version": "3.0.2",
            "purl": "pkg:brew/openssl@3.0.2",
            "licenses": [{"expression": "OpenSSL"}],
            "cpe": "cpe:2.3:a:openssl:openssl:3.0.2:*:*:*:*:*:*:*",
        },
        {
            "type": "application",
            "name": "git",
            "version": "2.42.0",
            "purl": "pkg:brew/git@2.42.0",
            "licenses": [],
        },
    ],
}


def test_parse_returns_scan_and_components():
    parser = SBOMParser()
    scan, components = parser.parse_cyclonedx(_NODE_ID, _MINIMAL_CYCLONEDX)
    assert scan.node_id == uuid.UUID(_NODE_ID)
    assert scan.syft_version == "1.2.3"
    assert scan.format == "cyclonedx"
    assert scan.component_count == 2
    assert len(components) == 2


def test_parse_scanned_at_is_utc():
    parser = SBOMParser()
    scan, _ = parser.parse_cyclonedx(_NODE_ID, _MINIMAL_CYCLONEDX)
    assert scan.scanned_at.tzinfo == timezone.utc


def test_parse_component_fields():
    parser = SBOMParser()
    _, components = parser.parse_cyclonedx(_NODE_ID, _MINIMAL_CYCLONEDX)
    openssl = next(c for c in components if c["name"] == "openssl")
    assert openssl["version"] == "3.0.2"
    assert openssl["purl"] == "pkg:brew/openssl@3.0.2"
    assert openssl["component_type"] == "library"
    assert openssl["licenses"] == ["OpenSSL"]
    assert "cpe:2.3:a:openssl" in openssl["cpes"][0]


def test_parse_component_no_license():
    parser = SBOMParser()
    _, components = parser.parse_cyclonedx(_NODE_ID, _MINIMAL_CYCLONEDX)
    git = next(c for c in components if c["name"] == "git")
    assert git["licenses"] == []
    assert git["cpes"] == []


def test_parse_missing_tools_defaults_syft_version_to_none():
    doc = {**_MINIMAL_CYCLONEDX, "metadata": {"timestamp": "2026-05-14T12:00:00Z"}}
    parser = SBOMParser()
    scan, _ = parser.parse_cyclonedx(_NODE_ID, doc)
    assert scan.syft_version is None


def test_parse_empty_components():
    doc = {**_MINIMAL_CYCLONEDX, "components": []}
    parser = SBOMParser()
    scan, components = parser.parse_cyclonedx(_NODE_ID, doc)
    assert scan.component_count == 0
    assert components == []


def test_parse_component_nested_license_id():
    doc = {
        **_MINIMAL_CYCLONEDX,
        "components": [
            {
                "type": "library",
                "name": "mit-lib",
                "version": "1.0",
                "licenses": [{"license": {"id": "MIT"}}],
            }
        ],
    }
    parser = SBOMParser()
    _, components = parser.parse_cyclonedx(_NODE_ID, doc)
    assert components[0]["licenses"] == ["MIT"]
