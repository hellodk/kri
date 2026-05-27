"""Celery tasks for iOS fleet tracking."""
import json
import urllib.request
from datetime import UTC, datetime

from sqlalchemy import select

from fleet_platform.db.session import get_sync_db
from fleet_platform.models.ios_tracking import JenkinsAgent
from fleet_platform.workers.celery_app import celery_app


def _check_jenkins_agent_sync(agent: JenkinsAgent) -> None:
    """Synchronous equivalent of ios_tracking_svc.check_jenkins_agent.

    Polls the Jenkins API and updates the agent row's status and
    last_checked_at in-place.  The caller is responsible for committing.
    """
    try:
        url = f"{agent.jenkins_url.rstrip('/')}/computer/{agent.agent_name}/api/json?tree=offline"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
        agent.status = "online" if data.get("offline") is False else "offline"
    except Exception:
        agent.status = "unknown"

    agent.last_checked_at = datetime.now(UTC)


@celery_app.task(
    name="fleet_platform.workers.ios_tasks.check_all_jenkins_agents",
    queue="maintenance",
)
def check_all_jenkins_agents():
    """Check all Jenkins agents using a synchronous DB session.

    Replaces the previous asyncio.run() pattern with get_sync_db() so the
    task runs safely inside a standard Celery prefork or thread worker.
    """
    with get_sync_db() as db:
        agents = db.execute(select(JenkinsAgent)).scalars().all()
        for agent in agents:
            _check_jenkins_agent_sync(agent)
        db.commit()
