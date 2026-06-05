import json
import os
import tempfile
import uuid
from unittest.mock import MagicMock, patch

_NODE_ID = str(uuid.uuid4())

_CYCLONEDX_DOC = {
    "bomFormat": "CycloneDX",
    "specVersion": "1.4",
    "metadata": {
        "timestamp": "2026-05-14T12:00:00Z",
        "tools": [{"name": "syft", "version": "1.2.3"}],
    },
    "components": [
        {"type": "library", "name": "openssl", "version": "3.0.2", "purl": "pkg:brew/openssl@3.0.2", "licenses": []},
    ],
}


def _make_temp_file(content: dict) -> str:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(content, f)
        return f.name


def test_index_sbom_deletes_temp_file():
    path = _make_temp_file(_CYCLONEDX_DOC)
    assert os.path.exists(path)

    mock_scan = MagicMock()
    mock_scan.id = uuid.uuid4()

    mock_db = MagicMock()
    mock_db.__enter__ = MagicMock(return_value=mock_db)
    mock_db.__exit__ = MagicMock(return_value=False)

    with (
        patch("fleet_platform.workers.sbom_tasks.get_sync_db", return_value=mock_db),
        patch("fleet_platform.workers.sbom_tasks.SBOMParser") as MockParser,
        patch("fleet_platform.workers.sbom_tasks.archive_old_scans") as mock_archive,
    ):
        MockParser.return_value.parse_cyclonedx.return_value = (mock_scan, [{"name": "openssl"}])
        from fleet_platform.workers.sbom_tasks import index_sbom

        result = index_sbom(_NODE_ID, path)

    assert not os.path.exists(path)
    assert result["status"] == "indexed"
    assert result["component_count"] == 1
    mock_archive.delay.assert_called_once_with(node_id=_NODE_ID, keep_count=3)


def test_index_sbom_missing_file_returns_error():
    with patch("fleet_platform.workers.sbom_tasks.get_sync_db"):
        from fleet_platform.workers.sbom_tasks import index_sbom

        result = index_sbom(_NODE_ID, "/tmp/nonexistent-sbom-file.json")
    assert result["status"] == "error"
    assert result["reason"] == "file_not_found"


def test_cleanup_old_sbom_scans_calls_db():
    mock_db = MagicMock()
    mock_db.__enter__ = MagicMock(return_value=mock_db)
    mock_db.__exit__ = MagicMock(return_value=False)
    mock_db.execute.return_value.rowcount = 5

    with patch("fleet_platform.workers.sbom_tasks.get_sync_db", return_value=mock_db):
        from fleet_platform.workers.sbom_tasks import cleanup_old_sbom_scans

        result = cleanup_old_sbom_scans(keep_count=3)

    assert result["deleted"] == 5
    mock_db.execute.assert_called_once()
    mock_db.commit.assert_called_once()
