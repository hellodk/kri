"""Tests for #497 — reap_orphaned_bootstraps updates Node.bootstrap_status."""

import uuid
from unittest.mock import MagicMock, patch


def test_reap_updates_node_bootstrap_status():
    """When stuck BootstrapRun rows exist, Node.bootstrap_status is set to 'failed'."""
    node_id = uuid.uuid4()

    mock_db = MagicMock()
    # First execute (SELECT node_ids) returns the node_id
    mock_db.execute.return_value.scalars.return_value.all.return_value = [node_id]

    def mock_context():
        cm = MagicMock()
        cm.__enter__ = MagicMock(return_value=mock_db)
        cm.__exit__ = MagicMock(return_value=False)
        return cm

    # Import and patch directly in the module
    import fleet_platform.workers.maintenance as maint_module

    with patch.object(maint_module, "get_sync_db", side_effect=mock_context):
        maint_module.reap_orphaned_bootstraps()

    # db.execute should have been called 3 times: SELECT, UPDATE BootstrapRun, UPDATE Node
    assert mock_db.execute.call_count == 3
    mock_db.commit.assert_called_once()


def test_reap_skips_node_update_when_nothing_reaped():
    """When no stuck BootstrapRun rows exist, Node UPDATE is not executed."""
    mock_db = MagicMock()
    mock_db.execute.return_value.scalars.return_value.all.return_value = []

    def mock_context():
        cm = MagicMock()
        cm.__enter__ = MagicMock(return_value=mock_db)
        cm.__exit__ = MagicMock(return_value=False)
        return cm

    # Import and patch directly in the module
    import fleet_platform.workers.maintenance as maint_module

    with patch.object(maint_module, "get_sync_db", side_effect=mock_context):
        maint_module.reap_orphaned_bootstraps()

    # Only 2 executes: SELECT + UPDATE BootstrapRun (Node UPDATE skipped)
    assert mock_db.execute.call_count == 2
    mock_db.commit.assert_called_once()
