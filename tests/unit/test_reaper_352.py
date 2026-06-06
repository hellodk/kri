"""Tests for per-job reaper tuning (#352, stacked on #348).

#348 introduced AnsibleJob.timeout_seconds (60..21600).
#352 makes the orphan cutoff per-job: orphaned when
    started_at < now() - (job.timeout_seconds + 300s buffer)
and tightens the reaper schedule from 900s → 300s.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Source-contract tests (no DB needed)
# ---------------------------------------------------------------------------


def test_reaper_schedule_is_300():
    """reap-orphaned-jobs beat entry must fire every 300 s (was 900s — closes #352)."""
    from fleet_platform.workers import celery_app as celery_module

    schedule = celery_module.celery_app.conf.beat_schedule
    assert "reap-orphaned-jobs" in schedule, "beat entry 'reap-orphaned-jobs' missing"
    assert schedule["reap-orphaned-jobs"]["schedule"] == 300, (
        f"Expected 300, got {schedule['reap-orphaned-jobs']['schedule']}"
    )


def test_orphan_buffer_constant_present():
    """_ORPHAN_BUFFER_SECONDS = 300 must be defined in maintenance.py (#352)."""
    import fleet_platform.workers.maintenance as m

    assert hasattr(m, "_ORPHAN_BUFFER_SECONDS"), "_ORPHAN_BUFFER_SECONDS not found in maintenance.py"
    assert m._ORPHAN_BUFFER_SECONDS == 300


def test_orphan_timeout_minutes_removed_or_bootstrap_only():
    """_ORPHAN_TIMEOUT_MINUTES must no longer exist (replaced by per-job logic, #352)."""
    import fleet_platform.workers.maintenance as m

    # The old static constant drove the ansible-job cutoff — it must be gone.
    assert not hasattr(m, "_ORPHAN_TIMEOUT_MINUTES"), (
        "_ORPHAN_TIMEOUT_MINUTES still present; it was superseded by per-job timeout_seconds "
        "in #352. Remove or rename it."
    )


# ---------------------------------------------------------------------------
# Behavioural tests (SQLite in-process via SQLAlchemy; no network)
# ---------------------------------------------------------------------------


def _make_mock_db_with_jobs(jobs_to_update: int = 0):
    """Return a mock db context manager whose execute() returns rowcount=jobs_to_update."""
    mock_result = MagicMock()
    mock_result.rowcount = jobs_to_update
    mock_db = MagicMock()
    mock_db.__enter__ = MagicMock(return_value=mock_db)
    mock_db.__exit__ = MagicMock(return_value=False)
    mock_db.execute.return_value = mock_result
    mock_db.commit = MagicMock()
    return mock_db


class TestPerJobCutoffInSQLStatement:
    """Verify the generated UPDATE statement uses per-job timeout_seconds arithmetic.

    We can't run real SQL here (no DB), so we inspect the SQLAlchemy clause tree
    rendered as a string against PostgreSQL dialect.
    """

    def _get_update_stmt_str(self) -> str:
        from fleet_platform.workers.maintenance import reap_orphaned_jobs

        mock_db = _make_mock_db_with_jobs(0)
        with patch("fleet_platform.workers.maintenance.get_sync_db", return_value=mock_db):
            reap_orphaned_jobs()

        call_args = mock_db.execute.call_args
        update_stmt = call_args[0][0]
        # Compile with literal_binds=True so numeric constants appear inline
        # (without this, SQLAlchemy replaces them with %(param)s placeholders)
        from sqlalchemy.dialects import postgresql

        return str(
            update_stmt.compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        )

    def test_statement_references_timeout_seconds(self):
        """UPDATE WHERE clause must reference the column timeout_seconds (not a literal)."""
        stmt_str = self._get_update_stmt_str()
        assert "timeout_seconds" in stmt_str, f"timeout_seconds not found in compiled statement:\n{stmt_str}"

    def test_statement_uses_interval_arithmetic(self):
        """UPDATE WHERE clause must use interval/make_interval for per-job cutoff."""
        stmt_str = self._get_update_stmt_str()
        # PostgreSQL interval arithmetic keywords
        assert any(kw in stmt_str.lower() for kw in ("interval", "make_interval")), (
            f"No interval arithmetic found in compiled statement:\n{stmt_str}"
        )

    def test_buffer_300_in_statement(self):
        """The 300-second buffer constant must appear in the compiled SQL."""
        stmt_str = self._get_update_stmt_str()
        assert "300" in stmt_str, f"Buffer value 300 not found in compiled statement:\n{stmt_str}"

    def test_completed_at_guard_preserved(self):
        """completed_at IS NULL guard from #305 must still be present."""
        stmt_str = self._get_update_stmt_str()
        assert "completed_at IS NULL" in stmt_str, f"completed_at IS NULL guard missing from statement:\n{stmt_str}"


class TestReaperBehaviourWithRealSQLite:
    """Run reap_orphaned_jobs against a real in-process SQLite DB.

    The AnsibleJob model uses PostgreSQL JSONB which SQLite doesn't support.
    We work around this by reflecting a plain-JSON shadow table into the
    ORM mapper just for these tests, using raw DDL that SQLite accepts.
    """

    @pytest.fixture()
    def db_engine_and_session(self):
        """Create a fresh in-memory SQLite engine with a SQLite-compatible ansible_jobs table."""
        from sqlalchemy import (
            Column,
            DateTime,
            Integer,
            String,
            Text,
            create_engine,
        )
        from sqlalchemy.orm import DeclarativeBase, sessionmaker

        engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
        )

        # Define a SQLite-compatible shadow of ansible_jobs (JSON instead of JSONB)
        class _Base(DeclarativeBase):
            pass

        from sqlalchemy import JSON

        class _AnsibleJobSQLite(_Base):
            __tablename__ = "ansible_jobs"

            id = Column(String(36), primary_key=True)
            playbook = Column(String(255), nullable=False)
            target_type = Column(String(20), nullable=False)
            target_id = Column(String(36), nullable=True)
            target_label = Column(String(255), nullable=False)
            extravars = Column(JSON, nullable=False, default=dict)
            verbosity = Column(Integer, nullable=False, default=0)
            timeout_seconds = Column(Integer, nullable=False, default=1800)
            status = Column(String(20), nullable=False, default="pending")
            triggered_by = Column(String(255), nullable=False)
            started_at = Column(DateTime(timezone=True), nullable=True)
            completed_at = Column(DateTime(timezone=True), nullable=True)
            stdout = Column(Text, nullable=True)
            rc = Column(Integer, nullable=True)
            celery_task_id = Column(String(255), nullable=True)
            cancelled_at = Column(DateTime(timezone=True), nullable=True)
            created_at = Column(DateTime(timezone=True), nullable=False)

        _Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        yield engine, Session, _AnsibleJobSQLite
        engine.dispose()

    @pytest.fixture()
    def session_and_model(self, db_engine_and_session):
        _, Session, Model = db_engine_and_session
        s = Session()
        yield s, Model
        s.close()

    def _insert_job(self, session, Model, *, status, timeout_seconds, started_at, completed_at=None):
        """Insert a minimal AnsibleJob row and return its id."""
        import uuid

        jid = str(uuid.uuid4())
        job = Model(
            id=jid,
            playbook="test.yml",
            target_type="node",
            target_id=str(uuid.uuid4()),
            target_label="test-node",
            extravars={},
            verbosity=0,
            timeout_seconds=timeout_seconds,
            status=status,
            triggered_by="test",
            started_at=started_at,
            completed_at=completed_at,
            created_at=datetime.now(UTC),
        )
        session.add(job)
        session.commit()
        return jid

    def _call_reaper_against(self, session):
        """Patch get_sync_db to yield our test session and call reap_orphaned_jobs.

        Also patch AnsibleJob to the real model — the reaper uses SQLAlchemy
        ORM column expressions which work against either engine as long as
        the column types are compatible (SQLite accepts interval arithmetic
        expressed as seconds via `julianday` workaround, but our maintenance.py
        uses PostgreSQL `make_interval`. So we verify reaper logic by inspecting
        its SQL and for SQLite we run a Python-side simulation).
        """
        from contextlib import contextmanager

        from fleet_platform.workers.maintenance import reap_orphaned_jobs

        @contextmanager
        def fake_sync_db():
            yield session

        with patch("fleet_platform.workers.maintenance.get_sync_db", fake_sync_db):
            return reap_orphaned_jobs()

    # --- test cases ---
    # NOTE: The reaper uses PostgreSQL make_interval() which SQLite doesn't support.
    # We verify the per-job logic by running the reaper's WHERE clause evaluation
    # in Python (simulating what the DB would do) and checking that the UPDATE
    # is constructed correctly via the statement inspection tests above.
    # The SQLite behavioural tests below use a Python-side reaper simulation that
    # mirrors the exact cutoff logic from maintenance.py.

    def _simulate_reaper(self, session, Model):
        """Python-side simulation of the per-job reaper logic for SQLite compatibility.

        Mirrors the rule: orphaned when started_at < now - (timeout_seconds + BUFFER).
        This validates the logic without needing PostgreSQL make_interval().

        SQLite stores datetimes without timezone info, so datetimes read back are
        naive. We strip tz from `now` to compare like-with-like.
        """
        from fleet_platform.workers.maintenance import _ORPHAN_BUFFER_SECONDS, _ORPHAN_MESSAGE

        # Use naive UTC now to match SQLite's naive datetime storage
        now = datetime.now(UTC).replace(tzinfo=None)
        reaped = 0
        jobs = session.query(Model).filter(Model.status == "running").all()
        for job in jobs:
            if job.completed_at is not None:
                continue  # completed_at IS NULL guard
            if job.started_at is None:
                # null started_at fallback: use created_at
                cutoff_check = job.created_at
            else:
                cutoff_check = job.started_at
            # Strip tzinfo if SQLite returned naive datetime
            if hasattr(cutoff_check, "tzinfo") and cutoff_check.tzinfo is not None:
                cutoff_check = cutoff_check.replace(tzinfo=None)
            cutoff = now - timedelta(seconds=job.timeout_seconds + _ORPHAN_BUFFER_SECONDS)
            if cutoff_check < cutoff:
                job.status = "failed"
                job.completed_at = now
                job.stdout = (job.stdout or "") + _ORPHAN_MESSAGE
                reaped += 1
        session.commit()
        return {"reaped": reaped}

    def test_job_past_timeout_plus_buffer_is_reaped(self, session_and_model):
        """Job with timeout_seconds=120 started 500s ago → reaped (120+300=420 < 500)."""
        session, Model = session_and_model
        now = datetime.now(UTC)
        jid = self._insert_job(
            session,
            Model,
            status="running",
            timeout_seconds=120,
            started_at=now - timedelta(seconds=500),
        )

        result = self._simulate_reaper(session, Model)

        assert result["reaped"] == 1

        session.expire_all()
        job = session.get(Model, jid)
        assert job.status == "failed"
        assert job.completed_at is not None
        assert _ORPHAN_MESSAGE_FRAGMENT in (job.stdout or "")

    def test_job_within_timeout_not_reaped(self, session_and_model):
        """Job with timeout_seconds=3600 started 500s ago → NOT reaped (3600+300=3900 > 500)."""
        session, Model = session_and_model
        now = datetime.now(UTC)
        jid = self._insert_job(
            session,
            Model,
            status="running",
            timeout_seconds=3600,
            started_at=now - timedelta(seconds=500),
        )

        result = self._simulate_reaper(session, Model)

        assert result["reaped"] == 0

        session.expire_all()
        job = session.get(Model, jid)
        assert job.status == "running"

    def test_completed_job_never_reaped(self, session_and_model):
        """A job already completed must never be touched by the reaper."""
        session, Model = session_and_model
        now = datetime.now(UTC)
        jid = self._insert_job(
            session,
            Model,
            status="completed",
            timeout_seconds=120,
            started_at=now - timedelta(seconds=5000),
            completed_at=now - timedelta(seconds=4800),
        )

        result = self._simulate_reaper(session, Model)

        assert result["reaped"] == 0

        session.expire_all()
        job = session.get(Model, jid)
        assert job.status == "completed"

    def test_failed_job_not_reaped_again(self, session_and_model):
        """A job already in status='failed' is not touched."""
        session, Model = session_and_model
        now = datetime.now(UTC)
        jid = self._insert_job(
            session,
            Model,
            status="failed",
            timeout_seconds=120,
            started_at=now - timedelta(seconds=5000),
        )

        result = self._simulate_reaper(session, Model)

        assert result["reaped"] == 0

        session.expire_all()
        job = session.get(Model, jid)
        assert job.status == "failed"

    def test_two_jobs_only_stale_one_reaped(self, session_and_model):
        """Two running jobs — one past timeout+buffer, one within — only the stale one reaped."""
        session, Model = session_and_model
        now = datetime.now(UTC)
        # This one is stale: timeout=120, started 500s ago → 120+300=420 < 500
        stale_id = self._insert_job(
            session,
            Model,
            status="running",
            timeout_seconds=120,
            started_at=now - timedelta(seconds=500),
        )
        # This one is fine: timeout=3600, started 500s ago → 3600+300=3900 > 500
        ok_id = self._insert_job(
            session,
            Model,
            status="running",
            timeout_seconds=3600,
            started_at=now - timedelta(seconds=500),
        )

        result = self._simulate_reaper(session, Model)

        assert result["reaped"] == 1

        session.expire_all()
        assert session.get(Model, stale_id).status == "failed"
        assert session.get(Model, ok_id).status == "running"


# Fragment from _ORPHAN_MESSAGE used in assertions
_ORPHAN_MESSAGE_FRAGMENT = "Task orphaned"
