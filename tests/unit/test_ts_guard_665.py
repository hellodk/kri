"""Unit tests for the TimescaleDB migration guard (#665).

These verify the catalog queries and boolean logic without a live database, by
stubbing ``alembic.op.get_bind``. The end-to-end "alembic upgrade head succeeds
on non-TimescaleDB Postgres" check is exercised in CI against a plain image.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from fleet_platform.db import ts_guard


def _bind_returning(row):
    bind = MagicMock()
    bind.exec_driver_sql.return_value.first.return_value = row
    return bind


def test_timescale_available_true_when_row_present():
    with patch.object(ts_guard.op, "get_bind", return_value=_bind_returning((1,))):
        assert ts_guard.timescale_available() is True


def test_timescale_available_false_when_absent():
    with patch.object(ts_guard.op, "get_bind", return_value=_bind_returning(None)):
        assert ts_guard.timescale_available() is False


def test_timescale_enabled_true_when_installed():
    with patch.object(ts_guard.op, "get_bind", return_value=_bind_returning((1,))):
        assert ts_guard.timescale_enabled() is True


def test_timescale_enabled_false_when_not_installed():
    with patch.object(ts_guard.op, "get_bind", return_value=_bind_returning(None)):
        assert ts_guard.timescale_enabled() is False


def test_available_queries_pg_available_extensions():
    bind = _bind_returning(None)
    with patch.object(ts_guard.op, "get_bind", return_value=bind):
        ts_guard.timescale_available()
    sql = bind.exec_driver_sql.call_args[0][0]
    assert "pg_available_extensions" in sql
    assert "timescaledb" in sql


def test_enabled_queries_pg_extension():
    bind = _bind_returning(None)
    with patch.object(ts_guard.op, "get_bind", return_value=bind):
        ts_guard.timescale_enabled()
    sql = bind.exec_driver_sql.call_args[0][0]
    assert "pg_extension" in sql
    assert "extname" in sql
