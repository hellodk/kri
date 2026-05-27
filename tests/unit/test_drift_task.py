import uuid
from unittest.mock import MagicMock, patch


def _make_mock_db():
    """Return a mock sync DB session context manager."""
    db = MagicMock()
    db.__enter__ = lambda s: s
    db.__exit__ = MagicMock(return_value=False)
    return db


def _make_mock_redis():
    """Return a mock Redis client that always acquires the lock."""
    r = MagicMock()
    r.set.return_value = True  # SETNX succeeds — lock acquired
    return r


def test_compute_drift_no_facts_returns_no_facts_status():
    from fleet_platform.workers.drift_tasks import compute_drift

    mock_db = _make_mock_db()
    mock_db.execute.return_value.scalar_one_or_none.return_value = None  # no NodeFact

    with patch("fleet_platform.workers.drift_tasks.get_sync_db", return_value=mock_db), \
         patch("fleet_platform.services.task_lock._get_sync_redis", return_value=_make_mock_redis()):
        result = compute_drift(str(uuid.uuid4()))

    assert result["status"] == "no_facts"


def test_compute_drift_no_baseline_returns_no_baseline_status():
    from unittest.mock import MagicMock

    from fleet_platform.workers.drift_tasks import compute_drift

    node_id = str(uuid.uuid4())
    mock_fact = MagicMock()
    mock_fact.grains = {"pkgs": {"git": "2.43.0"}}

    mock_db = _make_mock_db()
    # First execute → NodeFact found; subsequent → no baseline
    execute_results = [
        MagicMock(**{"scalar_one_or_none.return_value": mock_fact}),   # NodeFact
        MagicMock(**{"scalar_one_or_none.return_value": None}),        # node baseline
        MagicMock(**{"scalar_one_or_none.return_value": None}),        # group baseline
        MagicMock(**{"scalar_one_or_none.return_value": None}),        # global baseline
    ]
    mock_db.execute.side_effect = execute_results

    with patch("fleet_platform.workers.drift_tasks.get_sync_db", return_value=mock_db), \
         patch("fleet_platform.services.task_lock._get_sync_redis", return_value=_make_mock_redis()):
        result = compute_drift(node_id)

    assert result["status"] == "no_baseline"


def test_compute_drift_writes_drift_record_and_returns_score():
    from unittest.mock import MagicMock

    from fleet_platform.workers.drift_tasks import compute_drift

    node_id = str(uuid.uuid4())
    mock_fact = MagicMock()
    mock_fact.grains = {"pkgs": {"git": "2.43.0"}}

    mock_baseline = MagicMock()
    mock_baseline.id = uuid.uuid4()
    mock_baseline.state_json = {"packages": {"required": [{"name": "git"}]}}

    mock_node = MagicMock()
    mock_node.id = uuid.UUID(node_id)
    mock_node.drift_score = 0

    mock_db = _make_mock_db()
    execute_results = [
        MagicMock(**{"scalar_one_or_none.return_value": mock_fact}),       # NodeFact
        MagicMock(**{"scalar_one_or_none.return_value": None}),            # node baseline
        MagicMock(**{"scalar_one_or_none.return_value": None}),            # group baseline
        MagicMock(**{"scalar_one_or_none.return_value": mock_baseline}),   # global baseline
        MagicMock(**{"scalar_one_or_none.return_value": mock_node}),       # Node update
    ]
    mock_db.execute.side_effect = execute_results

    with patch("fleet_platform.workers.drift_tasks.get_sync_db", return_value=mock_db), \
         patch("fleet_platform.services.task_lock._get_sync_redis", return_value=_make_mock_redis()):
        result = compute_drift(node_id)

    assert result["status"] == "computed"
    assert "drift_score" in result
    assert result["drift_score"] == 0  # git is installed, no drift
    mock_db.add.assert_called()    # DriftRecord was added
    mock_db.commit.assert_called()
