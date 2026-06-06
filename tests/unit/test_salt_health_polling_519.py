"""Unit tests for salt-master health polling — issue #519, epic #523.

All DB and run_probe calls are mocked.  No live salt-api, DB, or Redis.
"""

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_master(**kwargs):
    """Build a SaltMaster-like SimpleNamespace without hitting the DB."""
    defaults = dict(
        id=uuid.uuid4(),
        name="test-master",
        enabled=True,
        is_default=False,
        address="salt.test.local",
        publish_port=4505,
        ret_port=4506,
        control_mode="salt_api",
        api_url="http://salt.test.local:8080",
        api_user="saltadmin",
        api_password_enc=None,
        api_eauth="pam",
        token_delivery="direct",
        status="unknown",
        last_checked_at=None,
        last_error=None,
        checks=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _healthy_probe_result():
    return {
        "status": "healthy",
        "checks": [
            {"check": "dns", "status": "pass", "detail": "Resolved", "latency_ms": 3},
            {"check": "tcp_publish", "status": "pass", "detail": "OK", "latency_ms": 5},
        ],
    }


def _unreachable_probe_result():
    return {
        "status": "unreachable",
        "checks": [
            {
                "check": "dns",
                "status": "fail",
                "detail": "DNS resolution failed",
                "latency_ms": 0,
            }
        ],
    }


# ---------------------------------------------------------------------------
# Tests: poll_salt_masters task
# ---------------------------------------------------------------------------


class TestPollSaltMasters:
    """Tests for fleet_platform.workers.maintenance.poll_salt_masters."""

    def _run_poll_with_masters(self, masters, probe_side_effect=None, probe_return=None):
        """Helper: run poll_salt_masters with a mocked DB session and mocked run_probe."""
        from fleet_platform.workers.maintenance import poll_salt_masters

        mock_db = MagicMock()
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)

        # Simulate db.execute(...).scalars().all() returning `masters`
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = masters
        mock_execute_result = MagicMock()
        mock_execute_result.scalars.return_value = mock_scalars
        mock_db.execute.return_value = mock_execute_result

        with (
            patch("fleet_platform.workers.maintenance.get_sync_db", return_value=mock_db),
            patch(
                "fleet_platform.workers.maintenance.asyncio.run",
                side_effect=probe_side_effect,
                return_value=probe_return,
            ) as mock_asyncio_run,
            patch("fleet_platform.workers.maintenance.sync_redis.Redis.from_url") as mock_redis_cls,
        ):
            mock_redis_cls.return_value = MagicMock()
            result = poll_salt_masters()

        return result, mock_asyncio_run, mock_db

    def test_poll_updates_healthy_master(self):
        """poll_salt_masters updates status/checks/last_checked_at from probe result."""
        master = _make_master(status="unknown")
        probe_result = _healthy_probe_result()

        _, mock_asyncio_run, mock_db = self._run_poll_with_masters(
            masters=[master],
            probe_side_effect=[probe_result],
        )

        assert master.status == "healthy"
        assert master.checks == probe_result["checks"]
        assert master.last_checked_at is not None
        assert master.last_error is None
        mock_db.commit.assert_called_once()

    def test_poll_sets_last_error_on_degraded(self):
        """poll_salt_masters sets last_error to the first failed check detail."""
        master = _make_master(status="unknown")
        probe_result = {
            "status": "degraded",
            "checks": [
                {"check": "dns", "status": "pass", "detail": "OK", "latency_ms": 2},
                {
                    "check": "salt_api_auth",
                    "status": "fail",
                    "detail": "Auth failed",
                    "latency_ms": 100,
                },
            ],
        }

        self._run_poll_with_masters(masters=[master], probe_side_effect=[probe_result])

        assert master.status == "degraded"
        assert master.last_error == "Auth failed"

    def test_poll_skips_unreachable_master_within_backoff_window(self):
        """An unreachable master checked recently (within backoff) is skipped."""
        # last_checked_at is 60 seconds ago — well within the backoff window
        recent_check = datetime.now(UTC) - timedelta(seconds=60)
        master = _make_master(status="unreachable", last_checked_at=recent_check)

        _, mock_asyncio_run, _ = self._run_poll_with_masters(masters=[master])

        # asyncio.run (i.e. run_probe) must NOT have been called
        mock_asyncio_run.assert_not_called()
        # Status must remain unreachable (unchanged)
        assert master.status == "unreachable"

    def test_poll_probes_unreachable_master_past_backoff_window(self):
        """An unreachable master whose last_checked_at is past the backoff window IS polled."""
        from fleet_platform.workers.maintenance import _SALT_UNREACHABLE_BACKOFF_SECONDS

        old_check = datetime.now(UTC) - timedelta(seconds=_SALT_UNREACHABLE_BACKOFF_SECONDS + 60)
        master = _make_master(status="unreachable", last_checked_at=old_check)
        probe_result = _healthy_probe_result()

        _, mock_asyncio_run, _ = self._run_poll_with_masters(masters=[master], probe_side_effect=[probe_result])

        mock_asyncio_run.assert_called_once()
        assert master.status == "healthy"

    def test_poll_skips_disabled_master(self):
        """A disabled master is never polled (the query filter handles it,
        but we verify via the DB execute call returning no masters)."""
        # DB returns no enabled masters — the where clause filtered them out
        _, mock_asyncio_run, _ = self._run_poll_with_masters(masters=[])

        mock_asyncio_run.assert_not_called()

    def test_poll_returns_summary_counts(self):
        """poll_salt_masters returns a dict with polled and skipped counts."""
        master = _make_master(status="unknown")
        probe_result = _healthy_probe_result()

        result, _, _ = self._run_poll_with_masters(masters=[master], probe_side_effect=[probe_result])

        assert "polled" in result
        assert "skipped" in result
        assert result["polled"] == 1
        assert result["skipped"] == 0

    def test_poll_redis_failure_does_not_fail_task(self):
        """If Redis setex raises, the task still completes and returns normally."""
        master = _make_master(status="unknown")
        probe_result = _healthy_probe_result()

        from fleet_platform.workers.maintenance import poll_salt_masters

        mock_db = MagicMock()
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [master]
        mock_execute_result = MagicMock()
        mock_execute_result.scalars.return_value = mock_scalars
        mock_db.execute.return_value = mock_execute_result

        mock_redis_instance = MagicMock()
        mock_redis_instance.setex.side_effect = Exception("Redis down")

        with (
            patch("fleet_platform.workers.maintenance.get_sync_db", return_value=mock_db),
            patch(
                "fleet_platform.workers.maintenance.asyncio.run",
                side_effect=[probe_result],
            ),
            patch(
                "fleet_platform.workers.maintenance.sync_redis.Redis.from_url",
                return_value=mock_redis_instance,
            ),
        ):
            result = poll_salt_masters()

        assert result["polled"] == 1

    def test_poll_unreachable_master_with_no_last_checked_is_polled(self):
        """An unreachable master with last_checked_at=None (never probed) is always polled."""
        master = _make_master(status="unreachable", last_checked_at=None)
        probe_result = _healthy_probe_result()

        _, mock_asyncio_run, _ = self._run_poll_with_masters(masters=[master], probe_side_effect=[probe_result])

        mock_asyncio_run.assert_called_once()


# ---------------------------------------------------------------------------
# Tests: GET /salt/masters/{id}/health
# ---------------------------------------------------------------------------


class TestGetSaltMasterHealth:
    """Tests for GET /api/v1/salt/masters/{master_id}/health."""

    def _make_async_db(self, master=None):
        """Return a mock AsyncSession that returns `master` on execute."""
        mock_db = MagicMock()

        async def _fake_execute(*args, **kwargs):
            result = MagicMock()
            result.scalar_one_or_none.return_value = master
            return result

        mock_db.execute = _fake_execute
        return mock_db

    @pytest.mark.asyncio
    async def test_health_returns_cached_row(self):
        """GET /health returns the cached DB row without calling run_probe."""
        master_id = uuid.uuid4()
        master = _make_master(
            id=master_id,
            status="healthy",
            last_checked_at=datetime.now(UTC) - timedelta(minutes=1),
            last_error=None,
            checks=[{"check": "dns", "status": "pass", "detail": "OK", "latency_ms": 2}],
        )

        from fleet_platform.api.routes.salt_masters import get_salt_master_health

        mock_db = self._make_async_db(master=master)

        with patch("fleet_platform.api.routes.salt_masters.run_probe") as mock_probe:
            response = await get_salt_master_health(
                master_id=master_id,
                db=mock_db,
                claims={"sub": "viewer@example.com", "roles": ["viewer"]},
            )

        mock_probe.assert_not_called()
        assert response["id"] == str(master_id)
        assert response["status"] == "healthy"
        assert response["last_error"] is None
        assert response["checks"] is not None

    @pytest.mark.asyncio
    async def test_health_returns_404_for_unknown_master(self):
        """GET /health returns 404 when the master_id does not exist."""
        from fastapi import HTTPException

        from fleet_platform.api.routes.salt_masters import get_salt_master_health

        mock_db = self._make_async_db(master=None)

        with pytest.raises(HTTPException) as exc_info:
            await get_salt_master_health(
                master_id=uuid.uuid4(),
                db=mock_db,
                claims={"sub": "viewer@example.com", "roles": ["viewer"]},
            )

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_health_does_not_call_run_probe(self):
        """Confirm run_probe is never invoked by the /health endpoint."""
        master_id = uuid.uuid4()
        master = _make_master(id=master_id, status="degraded", last_error="Auth failed")

        from fleet_platform.api.routes.salt_masters import get_salt_master_health

        mock_db = self._make_async_db(master=master)

        with patch("fleet_platform.api.routes.salt_masters.run_probe") as mock_probe:
            await get_salt_master_health(
                master_id=master_id,
                db=mock_db,
                claims={"sub": "admin@example.com", "roles": ["admin"]},
            )

        mock_probe.assert_not_called()
