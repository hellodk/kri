# fleet_platform/workers/playbook_tasks.py
"""Celery tasks for running arbitrary Ansible playbooks."""
import logging
import re
import tempfile
import uuid as _uuid
from datetime import UTC, datetime
from pathlib import Path

import ansible_runner
import yaml as _yaml
from sqlalchemy import select

from fleet_platform.db.session import get_sync_db
from fleet_platform.models.ansible_job import AnsibleJob
from fleet_platform.models.node import Node
from fleet_platform.workers.ansible_tasks import _get_bootstrap_settings
from fleet_platform.workers.celery_app import celery_app

_DEFAULT_PLAYBOOKS_DIR = Path(__file__).parent.parent.parent / "playbooks"

_log = logging.getLogger(__name__)
_SAFE_PATH_RE = re.compile(r'^[a-zA-Z0-9._\-]{1,128}$')


def _safe_label(label: str) -> str:
    """Sanitise a label used in file paths — prevents path traversal."""
    cleaned = re.sub(r'[^a-zA-Z0-9._\-]', '_', label)
    # Collapse any sequence of two or more dots to a single dot
    cleaned = re.sub(r'\.{2,}', '.', cleaned)
    cleaned = cleaned.strip('.')
    if not cleaned:
        cleaned = "unknown"
    return cleaned[:128]


def _get_playbooks_dir(db) -> Path:
    from sqlalchemy import select as _select

    from fleet_platform.models.platform_setting import PlatformSetting
    row = db.execute(
        _select(PlatformSetting).where(PlatformSetting.key == "playbooks_dir")
    ).scalar_one_or_none()
    if row and row.value:
        return Path(row.value)
    return _DEFAULT_PLAYBOOKS_DIR


def _write_static_inventory(tmpdir: str, hosts: list[tuple[str, str, str]]) -> str:
    lines = ["[targets]"]
    for hostname, ip, user in hosts:
        lines.append(f"{hostname} ansible_host={ip} ansible_user={user}")
    inv_path = Path(tmpdir) / "inventory.ini"
    inv_path.write_text("\n".join(lines))
    inv_path.chmod(0o600)  # not world-readable — contains IP addresses
    return str(inv_path)


def _write_var_file(path: Path, vars_dict: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_yaml.dump(vars_dict, default_flow_style=False, allow_unicode=True))



def _resolve_hosts(db, job: AnsibleJob, ssh_user: str) -> list[tuple[str, str, str]] | None:
    if job.target_type == "node":
        node = db.execute(
            select(Node).where(Node.id == _uuid.UUID(job.target_id))
        ).scalar_one_or_none()
        if not node or not node.ip_address:
            return None
        return [(node.hostname or node.minion_id, node.ip_address, ssh_user)]

    if job.target_type == "group":
        from fleet_platform.models.group import GroupMember
        memberships = db.execute(
            select(GroupMember).where(GroupMember.group_id == _uuid.UUID(job.target_id))
        ).scalars().all()
        node_ids = [m.node_id for m in memberships]
        if not node_ids:
            return []
        nodes = db.execute(
            select(Node).where(Node.id.in_(node_ids), Node.ip_address.isnot(None))
        ).scalars().all()
        return [(n.hostname or n.minion_id, n.ip_address, ssh_user) for n in nodes]

    return None


@celery_app.task(
    name="fleet_platform.workers.playbook_tasks.run_playbook",
    bind=True,
    max_retries=0,
    queue="maintenance",
)
def run_playbook(self, job_id: str, ssh_username: str | None = None, ssh_password: str | None = None) -> dict:
    job_uuid = _uuid.UUID(job_id)

    with get_sync_db() as db:
        job = db.execute(select(AnsibleJob).where(AnsibleJob.id == job_uuid)).scalar_one_or_none()
        if not job:
            return {"status": "error", "reason": "job_not_found"}
        job.status = "running"
        job.started_at = datetime.now(UTC)
        db.commit()
        _, _settings_ssh_user, _settings_ssh_password, _ = _get_bootstrap_settings(db)
        # Per-run credentials override global platform settings
        ssh_user = ssh_username or _settings_ssh_user
        ssh_password = _settings_ssh_password if ssh_password is None else ssh_password
        playbooks_dir = _get_playbooks_dir(db)

    with get_sync_db() as db:
        job = db.execute(select(AnsibleJob).where(AnsibleJob.id == job_uuid)).scalar_one()
        hosts = _resolve_hosts(db, job, ssh_user)

    if not hosts:
        with get_sync_db() as db:
            job = db.execute(select(AnsibleJob).where(AnsibleJob.id == job_uuid)).scalar_one()
            job.status = "failed"
            job.stdout = "No hosts with IP addresses found for the selected target."
            job.completed_at = datetime.now(UTC)
            db.commit()
        return {"status": "error", "reason": "no_hosts"}

    with get_sync_db() as db:
        job = db.execute(select(AnsibleJob).where(AnsibleJob.id == job_uuid)).scalar_one()
        if job.extravars:
            if job.target_type == "node" and hosts:
                hostname = _safe_label(hosts[0][0])
                vf = playbooks_dir / "host_vars" / f"{hostname}.yml"
                _write_var_file(vf, job.extravars)
            elif job.target_type == "group":
                vf = playbooks_dir / "group_vars" / f"{_safe_label(job.target_label)}.yml"
                _write_var_file(vf, job.extravars)

    playbook_path = playbooks_dir / job.playbook
    stdout_lines = []

    with tempfile.TemporaryDirectory(prefix="kri-playbook-") as tmpdir:
        inv_path = _write_static_inventory(tmpdir, hosts)
        result = ansible_runner.run(
            private_data_dir=tmpdir,
            playbook=str(playbook_path),
            inventory=inv_path,
            extravars=job.extravars or {},
            envvars={
                "ANSIBLE_USER": ssh_user,
                "ANSIBLE_PASSWORD": ssh_password,
                "ANSIBLE_COLLECTIONS_PATH": str(playbooks_dir / "collections" / "installed"),
            },
            quiet=False,
            rotate_artifacts=1,
            timeout=1200,
        )
        for event in result.events:
            msg = event.get("stdout", "")
            if msg:
                stdout_lines.append(msg)

    with get_sync_db() as db:
        job = db.execute(select(AnsibleJob).where(AnsibleJob.id == job_uuid)).scalar_one()
        job.status = "completed" if result.status == "successful" and result.rc == 0 else "failed"
        job.rc = result.rc
        job.stdout = "\n".join(stdout_lines) or f"rc={result.rc} status={result.status}"
        job.completed_at = datetime.now(UTC)
        db.commit()

    return {"status": result.status, "rc": result.rc, "job_id": job_id}
