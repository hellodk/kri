# tests/unit/test_ansible_tasks.py
# _write_pillar_file was removed in #509 (vestigial local pillar write).
# Tests for that function have been dropped.  bootstrap_node now delivers
# node_token exclusively via ansible-runner extravars.
import uuid
from unittest.mock import MagicMock, patch


def test_write_pillar_file_is_removed():
    """_write_pillar_file must no longer exist in ansible_tasks (#509)."""
    import fleet_platform.workers.ansible_tasks as mod

    assert not hasattr(mod, "_write_pillar_file"), "_write_pillar_file was re-introduced — it must stay removed (#509)"


def test_pillar_dir_writable_is_removed():
    """_pillar_dir_writable must no longer exist in ansible_tasks (#509)."""
    import fleet_platform.workers.ansible_tasks as mod

    assert not hasattr(mod, "_pillar_dir_writable"), (
        "_pillar_dir_writable was re-introduced — it must stay removed (#509)"
    )


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
