from unittest.mock import MagicMock, patch


def test_mark_stale_nodes_returns_counts():
    from fleet_platform.workers.maintenance import mark_stale_nodes

    mock_result = MagicMock()
    mock_result.rowcount = 3

    mock_session = MagicMock()
    mock_session.execute.return_value = mock_result
    mock_session.__enter__ = lambda s: s
    mock_session.__exit__ = MagicMock(return_value=False)

    with patch("fleet_platform.workers.maintenance.get_sync_db") as mock_db:
        mock_db.return_value = mock_session
        result = mark_stale_nodes()

    assert "stale" in result
    assert "offline" in result
    assert isinstance(result["stale"], int)
    assert isinstance(result["offline"], int)


def test_mark_stale_nodes_calls_commit():
    from fleet_platform.workers.maintenance import mark_stale_nodes

    mock_result = MagicMock()
    mock_result.rowcount = 0
    mock_session = MagicMock()
    mock_session.execute.return_value = mock_result
    mock_session.__enter__ = lambda s: s
    mock_session.__exit__ = MagicMock(return_value=False)

    with patch("fleet_platform.workers.maintenance.get_sync_db") as mock_db:
        mock_db.return_value = mock_session
        mark_stale_nodes()

    mock_session.commit.assert_called_once()
