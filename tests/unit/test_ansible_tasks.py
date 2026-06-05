# tests/unit/test_ansible_tasks.py
import uuid
from unittest.mock import MagicMock, patch


def _make_mock_db(node):
    mock_db = MagicMock()
    mock_db.__enter__ = MagicMock(return_value=mock_db)
    mock_db.__exit__ = MagicMock(return_value=False)
    mock_db.execute.return_value.scalar_one_or_none.return_value = node
    mock_db.execute.return_value.scalar_one.return_value = node
    return mock_db


def test_write_pillar_file_creates_correct_content(tmp_path):
    from fleet_platform.workers.ansible_tasks import _write_pillar_file

    _write_pillar_file(
        pillar_dir=str(tmp_path),
        minion_id="mac-01.local",
        ingest_url="http://10.0.0.1:8000/api/v1/ingest",
        node_token="mytoken123",
    )
    sls = (tmp_path / "mac-01.local.sls").read_text()
    assert "mytoken123" in sls
    assert "fleet_platform" in sls
    assert "http://10.0.0.1:8000/api/v1/ingest" in sls


def test_write_pillar_file_creates_top_sls(tmp_path):
    from fleet_platform.workers.ansible_tasks import _write_pillar_file

    _write_pillar_file(str(tmp_path), "node-01", "http://x/ingest", "tok")
    top = (tmp_path / "top.sls").read_text()
    assert "node-01" in top


def test_write_pillar_file_updates_existing_top_sls(tmp_path):
    from fleet_platform.workers.ansible_tasks import _write_pillar_file

    # Write initial top.sls
    (tmp_path / "top.sls").write_text("base:\n  'node-99':\n    - node-99\n")
    _write_pillar_file(str(tmp_path), "node-01", "http://x/ingest", "tok")
    top = (tmp_path / "top.sls").read_text()
    assert "node-99" in top  # existing entry preserved
    assert "node-01" in top  # new entry added


def test_bootstrap_node_missing_node_returns_error():
    mock_db = MagicMock()
    mock_db.__enter__ = MagicMock(return_value=mock_db)
    mock_db.__exit__ = MagicMock(return_value=False)
    mock_db.execute.return_value.scalar_one_or_none.return_value = None

    with patch("fleet_platform.workers.ansible_tasks.get_sync_db", return_value=mock_db):
        from fleet_platform.workers.ansible_tasks import bootstrap_node

        result = bootstrap_node(str(uuid.uuid4()), "10.0.1.50")

    assert result["status"] == "error"
    assert result["reason"] == "node_not_found"
