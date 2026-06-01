"""Celery task: deploy or remove a mobileconfig profile on a fleet node via Ansible."""
from __future__ import annotations

import logging
import tempfile
import uuid
from pathlib import Path

import ansible_runner
from sqlalchemy import select

from fleet_platform.db.session import get_sync_db
from fleet_platform.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

_PLAYBOOKS_DIR = Path(__file__).parent.parent.parent / "playbooks"


@celery_app.task(
    name="fleet_platform.workers.mobileconfig_tasks.deploy_mobileconfig_task",
    bind=True,
    max_retries=2,
    queue="maintenance",
)
def deploy_mobileconfig_task(
    self,
    *,
    profile_id: str,
    profile_name: str,
    profile_payload_xml: str,
    profile_identifier: str,
    node_hostname: str,
    action: str,  # 'install' | 'remove'
    log_id: str,
) -> dict:
    """Run deploy_mobileconfig.yml via ansible-runner against a single node.

    Updates ProfileDeploymentLog.status to 'success' or 'failed' after completion.
    Retries up to 2 times on unexpected exceptions (not on Ansible rc != 0).
    """
    from fleet_platform.models.mobileconfig import ProfileDeploymentLog

    log_uuid = uuid.UUID(log_id)

    with get_sync_db() as db:
        log = db.execute(
            select(ProfileDeploymentLog).where(ProfileDeploymentLog.id == log_uuid)
        ).scalar_one_or_none()
        if log:
            log.status = "running"
            db.commit()

    try:
        with tempfile.TemporaryDirectory(prefix="kri-mobileconfig-") as run_dir:
            result = ansible_runner.run(
                project_dir=str(_PLAYBOOKS_DIR),
                playbook="deploy_mobileconfig.yml",
                inventory=str(_PLAYBOOKS_DIR / "inventory"),
                extravars={
                    "profile_action": action,
                    "profile_name": profile_name,
                    "profile_payload_xml": profile_payload_xml,
                    "profile_identifier": profile_identifier,
                    "target_hosts": node_hostname,
                },
                artifact_dir=run_dir,
                quiet=True,
            )

        success = result.rc == 0 and result.status == "successful"
        error_msg = None if success else f"ansible-runner rc={result.rc} status={result.status}"

        with get_sync_db() as db:
            log = db.execute(
                select(ProfileDeploymentLog).where(ProfileDeploymentLog.id == log_uuid)
            ).scalar_one_or_none()
            if log:
                log.status = "success" if success else "failed"
                if error_msg:
                    log.error = error_msg[:1000]
                db.commit()

        return {
            "status": "success" if success else "failed",
            "rc": result.rc,
            "node": node_hostname,
            "action": action,
        }

    except Exception as exc:
        error_msg = str(exc)
        with get_sync_db() as db:
            log = db.execute(
                select(ProfileDeploymentLog).where(ProfileDeploymentLog.id == log_uuid)
            ).scalar_one_or_none()
            if log:
                log.status = "failed"
                log.error = error_msg[:1000]
                db.commit()
        raise self.retry(exc=exc, countdown=30)
