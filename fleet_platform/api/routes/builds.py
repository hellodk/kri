# fleet_platform/api/routes/builds.py
import hmac

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.api.deps import get_db
from fleet_platform.core.auth import require_role
from fleet_platform.models.jenkins_build_event import JenkinsBuildEvent
from fleet_platform.schemas.builds import JenkinsBuildIngestPayload, JenkinsBuildResponse
from fleet_platform.services.platform_settings_svc import JENKINS_INGEST_SECRET, get_setting

router = APIRouter(prefix="/api/v1/builds")


async def _verify_jenkins_secret(
    x_jenkins_secret: str | None,
    db: AsyncSession,
) -> None:
    """Raise 401 if header is missing or does not match the stored secret."""
    if not x_jenkins_secret:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-Jenkins-Secret",
        )
    expected = await get_setting(db, JENKINS_INGEST_SECRET)
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Jenkins ingest secret not configured — set it in Settings",
        )
    if not hmac.compare_digest(x_jenkins_secret, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid X-Jenkins-Secret",
        )


@router.post("/ingest")
async def ingest_build(
    payload: JenkinsBuildIngestPayload,
    x_jenkins_secret: str | None = Header(alias="X-Jenkins-Secret", default=None),
    db: AsyncSession = Depends(get_db),
):
    """Jenkins calls this after every build. Idempotent: duplicate (job_name, build_number) is a no-op."""
    await _verify_jenkins_secret(x_jenkins_secret, db)

    # Check idempotency: skip if already ingested
    existing = await db.execute(
        select(JenkinsBuildEvent).where(
            JenkinsBuildEvent.job_name == payload.job_name,
            JenkinsBuildEvent.build_number == payload.build_number,
        )
    )
    if existing.scalar_one_or_none() is not None:
        return {"status": "ok", "detail": "already ingested"}

    event = JenkinsBuildEvent(
        job_name=payload.job_name,
        build_number=payload.build_number,
        result=payload.result,
        duration_ms=payload.duration_ms,
        started_at=payload.started_at,
        test_pass=payload.test_pass,
        test_fail=payload.test_fail,
        test_total=payload.test_total,
        node_name=payload.node_name,
        branch=payload.branch,
    )
    db.add(event)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        return {"status": "ok", "detail": "already ingested"}

    return {"status": "ok", "id": str(event.id)}


@router.get("/recent", response_model=list[JenkinsBuildResponse])
async def list_recent_builds(
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("viewer")),
):
    """Return the most recent Jenkins build events (newest first)."""
    result = await db.execute(
        select(JenkinsBuildEvent).order_by(JenkinsBuildEvent.started_at.desc()).limit(min(limit, 200))
    )
    builds = result.scalars().all()
    return [
        JenkinsBuildResponse(
            id=str(b.id),
            job_name=b.job_name,
            build_number=b.build_number,
            result=b.result,
            duration_ms=b.duration_ms,
            started_at=b.started_at,
            test_pass=b.test_pass,
            test_fail=b.test_fail,
            test_total=b.test_total,
            node_name=b.node_name,
            branch=b.branch,
        )
        for b in builds
    ]


@router.post("/digest/send-now")
async def trigger_digest_now(
    _: dict = Depends(require_role("admin")),
):
    """Trigger the weekly digest immediately. Dispatches as a Celery task (returns task_id)."""
    from fleet_platform.workers.digest_tasks import weekly_digest

    task = weekly_digest.delay()
    return {"status": "queued", "task_id": task.id}
