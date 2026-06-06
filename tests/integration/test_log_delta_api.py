# tests/integration/test_log_delta_api.py
"""Integration tests for ?from_byte delta polling on GET /api/v1/ansible/jobs/{id} (#371)."""

import uuid

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.models.ansible_job import AnsibleJob

# ---------------------------------------------------------------------------
# Fixture: a job row with stdout that includes a running marker
# ---------------------------------------------------------------------------

STDOUT_BASE = "PLAY [all]\n\nTASK [Gathering Facts]\nok: [host1]\n\nTASK [Install salt]\nchanged: [host1]"
RUNNING_TASK = "Deploy config"
STDOUT_WITH_MARKER = STDOUT_BASE + f"\n\n[running: {RUNNING_TASK}]"


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def delta_job(db_session: AsyncSession):
    job = AnsibleJob(
        id=uuid.uuid4(),
        playbook="test_delta.yml",
        target_type="node",
        target_label="test-host",
        target_id=None,
        extravars={},
        status="running",
        triggered_by="test-user",
        stdout=STDOUT_WITH_MARKER,
        verbosity=0,
    )
    db_session.add(job)
    await db_session.commit()
    await db_session.refresh(job)
    yield job
    await db_session.delete(job)
    await db_session.commit()


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def completed_job(db_session: AsyncSession):
    """A job with plain stdout and no marker."""
    job = AnsibleJob(
        id=uuid.uuid4(),
        playbook="test_completed.yml",
        target_type="node",
        target_label="test-host",
        target_id=None,
        extravars={},
        status="completed",
        triggered_by="test-user",
        stdout="All tasks completed\nDone.",
        verbosity=0,
    )
    db_session.add(job)
    await db_session.commit()
    await db_session.refresh(job)
    yield job
    await db_session.delete(job)
    await db_session.commit()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_get_job_without_from_byte_returns_full_raw(
    viewer_client: AsyncClient,
    delta_job: AnsibleJob,
):
    """Without ?from_byte the response stdout is the full raw string including the marker."""
    r = await viewer_client.get(f"/api/v1/ansible/jobs/{delta_job.id}")
    assert r.status_code == 200
    body = r.json()
    assert body["stdout"] == STDOUT_WITH_MARKER
    # No delta fields in full-raw mode
    assert body["stdout_total_len"] is None
    assert body["running_task"] is None


async def test_get_job_from_byte_0_returns_base_and_meta(
    viewer_client: AsyncClient,
    delta_job: AnsibleJob,
):
    """?from_byte=0 returns the full base (marker stripped), total len, and running_task."""
    r = await viewer_client.get(f"/api/v1/ansible/jobs/{delta_job.id}?from_byte=0")
    assert r.status_code == 200
    body = r.json()
    # stdout == base (no marker)
    assert body["stdout"] == STDOUT_BASE
    assert body["stdout_total_len"] == len(STDOUT_BASE)
    assert body["running_task"] == RUNNING_TASK


async def test_get_job_from_byte_midway_returns_correct_slice(
    viewer_client: AsyncClient,
    delta_job: AnsibleJob,
):
    """from_byte mid-way through the base returns only the tail of the base."""
    offset = len("PLAY [all]\n\nTASK [Gathering Facts]\n")
    r = await viewer_client.get(f"/api/v1/ansible/jobs/{delta_job.id}?from_byte={offset}")
    assert r.status_code == 200
    body = r.json()
    expected_delta = STDOUT_BASE[offset:]
    assert body["stdout"] == expected_delta
    assert body["stdout_total_len"] == len(STDOUT_BASE)
    assert body["running_task"] == RUNNING_TASK


async def test_get_job_from_byte_at_end_returns_empty_stdout(
    viewer_client: AsyncClient,
    delta_job: AnsibleJob,
):
    """from_byte >= total base len returns empty stdout with correct total."""
    r = await viewer_client.get(f"/api/v1/ansible/jobs/{delta_job.id}?from_byte={len(STDOUT_BASE)}")
    assert r.status_code == 200
    body = r.json()
    assert body["stdout"] == ""
    assert body["stdout_total_len"] == len(STDOUT_BASE)


async def test_get_job_from_byte_beyond_end_returns_empty_stdout(
    viewer_client: AsyncClient,
    delta_job: AnsibleJob,
):
    """from_byte far beyond base length returns empty stdout."""
    r = await viewer_client.get(f"/api/v1/ansible/jobs/{delta_job.id}?from_byte=99999")
    assert r.status_code == 200
    body = r.json()
    assert body["stdout"] == ""
    assert body["stdout_total_len"] == len(STDOUT_BASE)


async def test_get_job_from_byte_negative_returns_422(
    viewer_client: AsyncClient,
    delta_job: AnsibleJob,
):
    """Negative from_byte must be rejected with 422."""
    r = await viewer_client.get(f"/api/v1/ansible/jobs/{delta_job.id}?from_byte=-1")
    assert r.status_code == 422


async def test_get_job_no_marker_from_byte_0(
    viewer_client: AsyncClient,
    completed_job: AnsibleJob,
):
    """Job with no running marker: base == full stdout, running_task is None."""
    r = await viewer_client.get(f"/api/v1/ansible/jobs/{completed_job.id}?from_byte=0")
    assert r.status_code == 200
    body = r.json()
    assert body["stdout"] == completed_job.stdout
    assert body["stdout_total_len"] == len(completed_job.stdout)
    assert body["running_task"] is None
