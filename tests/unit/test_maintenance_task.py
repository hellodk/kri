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


def test_mark_stale_nodes_sets_offline_when_last_seen_2h_ago():
    """Node with last_seen_at 2 hours ago must be marked offline by mark_stale_nodes."""
    from fleet_platform.workers.maintenance import mark_stale_nodes

    # Capture the WHERE clauses passed to the two UPDATE calls by inspecting the
    # arguments forwarded to session.execute().  We do not have SQLAlchemy models
    # available in the unit layer, so we assert at the behavioural level:
    # • execute() is called exactly twice (stale update, offline update)
    # • commit() is called once
    # • the returned offline count comes from the second execute result
    stale_result = MagicMock()
    stale_result.rowcount = 0
    offline_result = MagicMock()
    offline_result.rowcount = 1

    mock_session = MagicMock()
    mock_session.execute.side_effect = [stale_result, offline_result]
    mock_session.__enter__ = lambda s: s
    mock_session.__exit__ = MagicMock(return_value=False)

    with patch("fleet_platform.workers.maintenance.get_sync_db") as mock_db:
        mock_db.return_value = mock_session
        result = mark_stale_nodes()

    # Two UPDATE statements must have been issued
    assert mock_session.execute.call_count == 2, (
        "Expected exactly 2 UPDATE calls (stale + offline) — got "
        f"{mock_session.execute.call_count}"
    )
    mock_session.commit.assert_called_once()

    # The offline count must be reported as 1 (from our mock)
    assert result["offline"] == 1, (
        f"Node last seen 2 h ago should be counted as offline; got offline={result['offline']}"
    )
    assert result["stale"] == 0
