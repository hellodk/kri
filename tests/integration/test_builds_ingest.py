# tests/integration/test_builds_ingest.py
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio


async def _clean_setting(db_session: AsyncSession, key: str) -> None:
    """Remove a platform_settings row if it exists."""
    from sqlalchemy import delete

    from fleet_platform.models.platform_setting import PlatformSetting
    await db_session.execute(delete(PlatformSetting).where(PlatformSetting.key == key))
    await db_session.commit()


async def _clean_build(db_session: AsyncSession, job_name: str, build_number: int) -> None:
    """Remove a jenkins_build_event row if it exists."""
    from sqlalchemy import delete

    from fleet_platform.models.jenkins_build_event import JenkinsBuildEvent
    await db_session.execute(
        delete(JenkinsBuildEvent).where(
            JenkinsBuildEvent.job_name == job_name,
            JenkinsBuildEvent.build_number == build_number,
        )
    )
    await db_session.commit()


async def test_ingest_build_requires_secret(client: AsyncClient):
    payload = {
        "job_name": "my-pipeline",
        "build_number": 1,
        "result": "SUCCESS",
        "started_at": datetime.now(UTC).isoformat(),
    }
    resp = await client.post("/api/v1/builds/ingest", json=payload)
    assert resp.status_code == 401


async def test_ingest_build_wrong_secret(client: AsyncClient, db_session: AsyncSession):
    await _clean_setting(db_session, "jenkins_ingest_secret")

    from fleet_platform.models.platform_setting import PlatformSetting
    db_session.add(PlatformSetting(
        key="jenkins_ingest_secret", value="correct-secret-t2", is_encrypted=False
    ))
    await db_session.commit()

    payload = {
        "job_name": "my-pipeline",
        "build_number": 2001,
        "result": "SUCCESS",
        "started_at": datetime.now(UTC).isoformat(),
    }
    resp = await client.post(
        "/api/v1/builds/ingest",
        json=payload,
        headers={"X-Jenkins-Secret": "wrong-secret"},
    )
    assert resp.status_code == 401

    # Cleanup
    await _clean_setting(db_session, "jenkins_ingest_secret")


async def test_ingest_build_success(client: AsyncClient, db_session: AsyncSession):
    from sqlalchemy import select

    from fleet_platform.models.jenkins_build_event import JenkinsBuildEvent
    from fleet_platform.models.platform_setting import PlatformSetting

    await _clean_setting(db_session, "jenkins_ingest_secret")
    await _clean_build(db_session, "deploy-prod", 42)

    secret = "test-secret-abc123"
    db_session.add(PlatformSetting(
        key="jenkins_ingest_secret", value=secret, is_encrypted=False
    ))
    await db_session.commit()

    payload = {
        "job_name": "deploy-prod",
        "build_number": 42,
        "result": "SUCCESS",
        "duration_ms": 12300,
        "started_at": datetime.now(UTC).isoformat(),
        "test_pass": 97,
        "test_fail": 3,
        "test_total": 100,
        "node_name": "mac-mini-1",
        "branch": "main",
    }
    resp = await client.post(
        "/api/v1/builds/ingest",
        json=payload,
        headers={"X-Jenkins-Secret": secret},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"

    result = await db_session.execute(
        select(JenkinsBuildEvent).where(
            JenkinsBuildEvent.job_name == "deploy-prod",
            JenkinsBuildEvent.build_number == 42,
        )
    )
    event = result.scalar_one()
    assert event.result == "SUCCESS"
    assert event.test_pass == 97

    # Cleanup
    await _clean_setting(db_session, "jenkins_ingest_secret")
    await _clean_build(db_session, "deploy-prod", 42)


async def test_ingest_build_idempotent(client: AsyncClient, db_session: AsyncSession):
    """Duplicate ingest with same job_name + build_number returns 200 without error."""
    from fleet_platform.models.platform_setting import PlatformSetting

    await _clean_setting(db_session, "jenkins_ingest_secret")
    await _clean_build(db_session, "ci-test", 9001)

    secret = "idempotent-secret"
    db_session.add(PlatformSetting(
        key="jenkins_ingest_secret", value=secret, is_encrypted=False
    ))
    await db_session.commit()

    payload = {
        "job_name": "ci-test",
        "build_number": 9001,
        "result": "FAILURE",
        "started_at": datetime.now(UTC).isoformat(),
    }
    headers = {"X-Jenkins-Secret": secret}
    resp1 = await client.post("/api/v1/builds/ingest", json=payload, headers=headers)
    resp2 = await client.post("/api/v1/builds/ingest", json=payload, headers=headers)
    assert resp1.status_code == 200
    assert resp2.status_code == 200
    assert resp2.json()["status"] == "ok"

    # Cleanup
    await _clean_setting(db_session, "jenkins_ingest_secret")
    await _clean_build(db_session, "ci-test", 9001)
