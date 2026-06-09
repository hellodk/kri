"""Unit tests for P1 audit #639 — llm_query_log retention + response truncation."""

from pathlib import Path
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# cleanup_old_llm_logs beat task
# ---------------------------------------------------------------------------


def test_cleanup_old_llm_logs_returns_deleted_count():
    """cleanup_old_llm_logs must return {"deleted": rowcount} from the DB result."""
    from fleet_platform.workers.maintenance import cleanup_old_llm_logs

    mock_result = MagicMock()
    mock_result.rowcount = 3

    mock_session = MagicMock()
    mock_session.execute.return_value = mock_result
    mock_session.__enter__ = lambda s: s
    mock_session.__exit__ = MagicMock(return_value=False)

    with patch("fleet_platform.db.session.get_sync_db") as mock_db:
        mock_db.return_value = mock_session
        result = cleanup_old_llm_logs()

    assert result == {"deleted": 3}


def test_cleanup_old_llm_logs_calls_commit():
    """cleanup_old_llm_logs must call db.commit() after the DELETE."""
    from fleet_platform.workers.maintenance import cleanup_old_llm_logs

    mock_result = MagicMock()
    mock_result.rowcount = 0

    mock_session = MagicMock()
    mock_session.execute.return_value = mock_result
    mock_session.__enter__ = lambda s: s
    mock_session.__exit__ = MagicMock(return_value=False)

    with patch("fleet_platform.db.session.get_sync_db") as mock_db:
        mock_db.return_value = mock_session
        cleanup_old_llm_logs()

    mock_session.commit.assert_called_once()


def test_cleanup_old_llm_logs_issues_delete_on_llm_query_log():
    """The DELETE statement must target the llm_query_log table."""
    from sqlalchemy import Delete

    from fleet_platform.workers.maintenance import cleanup_old_llm_logs

    mock_result = MagicMock()
    mock_result.rowcount = 2

    executed_stmts: list = []

    mock_session = MagicMock()
    mock_session.execute.side_effect = lambda stmt: (executed_stmts.append(stmt), mock_result)[1]
    mock_session.__enter__ = lambda s: s
    mock_session.__exit__ = MagicMock(return_value=False)

    with patch("fleet_platform.db.session.get_sync_db") as mock_db:
        mock_db.return_value = mock_session
        cleanup_old_llm_logs()

    assert len(executed_stmts) == 1, "Expected exactly one statement to be executed"
    stmt = executed_stmts[0]
    # The statement must be a DELETE targeting llm_query_log
    assert isinstance(stmt, Delete), f"Expected a DELETE statement, got {type(stmt)}"
    table_name = stmt.table.name
    assert table_name == "llm_query_log", f"DELETE targeted wrong table: {table_name!r}"


def test_cleanup_old_llm_logs_zero_rowcount_becomes_zero():
    """When rowcount is 0 (or None), deleted must be 0, not falsy None."""
    from fleet_platform.workers.maintenance import cleanup_old_llm_logs

    mock_result = MagicMock()
    mock_result.rowcount = 0

    mock_session = MagicMock()
    mock_session.execute.return_value = mock_result
    mock_session.__enter__ = lambda s: s
    mock_session.__exit__ = MagicMock(return_value=False)

    with patch("fleet_platform.db.session.get_sync_db") as mock_db:
        mock_db.return_value = mock_session
        result = cleanup_old_llm_logs()

    assert result == {"deleted": 0}


# ---------------------------------------------------------------------------
# create_query_log response truncation
# ---------------------------------------------------------------------------


def test_max_logged_response_chars_constant_exists():
    """_MAX_LOGGED_RESPONSE_CHARS must be defined in llm_svc."""
    from fleet_platform.services import llm_svc

    assert hasattr(llm_svc, "_MAX_LOGGED_RESPONSE_CHARS"), "_MAX_LOGGED_RESPONSE_CHARS constant missing from llm_svc"
    assert llm_svc._MAX_LOGGED_RESPONSE_CHARS == 8000


def test_response_truncated_to_max_logged_chars():
    """Pure truncation contract: a response longer than the limit is sliced to exactly the limit."""
    from fleet_platform.services.llm_svc import _MAX_LOGGED_RESPONSE_CHARS

    long_response = "x" * 9000
    stored = long_response[:_MAX_LOGGED_RESPONSE_CHARS]
    assert len(stored) == 8000


def test_response_not_truncated_when_within_limit():
    """A response shorter than the limit must be stored unchanged."""
    from fleet_platform.services.llm_svc import _MAX_LOGGED_RESPONSE_CHARS

    short_response = "hello"
    stored = short_response[:_MAX_LOGGED_RESPONSE_CHARS]
    assert stored == short_response


def test_none_response_not_truncated():
    """None response must stay None — no AttributeError from slicing."""
    from fleet_platform.services.llm_svc import _MAX_LOGGED_RESPONSE_CHARS

    response = None
    stored = response[:_MAX_LOGGED_RESPONSE_CHARS] if response else None
    assert stored is None


# Source-contract: create_query_log applies the cap to response=
def test_create_query_log_caps_response_source_contract():
    """create_query_log must store response truncated to _MAX_LOGGED_RESPONSE_CHARS."""
    import ast

    svc_path = Path(__file__).resolve().parents[2] / "fleet_platform" / "services" / "llm_svc.py"
    source = svc_path.read_text()
    tree = ast.parse(source)

    # Find the create_query_log function and verify the response= assignment
    found_cap = False
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "create_query_log":
            func_src = ast.get_source_segment(source, node) or ""
            # The assignment must reference _MAX_LOGGED_RESPONSE_CHARS in the response kwarg
            assert "_MAX_LOGGED_RESPONSE_CHARS" in func_src, (
                "create_query_log does not reference _MAX_LOGGED_RESPONSE_CHARS"
            )
            found_cap = True
            break

    assert found_cap, "create_query_log function not found in llm_svc.py"


# ---------------------------------------------------------------------------
# beat_schedule source-contract: cleanup-old-llm-logs entry present
# ---------------------------------------------------------------------------


def test_beat_schedule_has_cleanup_old_llm_logs_entry():
    """celery_app.py beat_schedule must contain cleanup-old-llm-logs on queue maintenance."""
    from fleet_platform.workers.celery_app import celery_app

    schedule = celery_app.conf.beat_schedule
    assert "cleanup-old-llm-logs" in schedule, "cleanup-old-llm-logs entry missing from beat_schedule"
    entry = schedule["cleanup-old-llm-logs"]
    assert entry["task"] == "fleet_platform.workers.maintenance.cleanup_old_llm_logs"
    assert entry.get("options", {}).get("queue") == "maintenance"
