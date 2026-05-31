# fleet_platform/workers/playbook_tasks.py
"""Celery tasks for running arbitrary Ansible playbooks."""
import logging
import re
import tempfile
import time
import uuid as _uuid
from datetime import UTC, datetime
from pathlib import Path

import ansible_runner
import yaml as _yaml
from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy import select

from fleet_platform.db.session import get_sync_db
from fleet_platform.models.ansible_job import AnsibleJob
from fleet_platform.models.node import Node
from fleet_platform.workers.ansible_tasks import _get_bootstrap_settings
from fleet_platform.workers.celery_app import celery_app

_DEFAULT_PLAYBOOKS_DIR = Path(__file__).parent.parent.parent / "playbooks"

_log = logging.getLogger(__name__)
_SAFE_PATH_RE = re.compile(r'^[a-zA-Z0-9._\-]{1,128}$')
_LOG_BATCH_INTERVAL = 30  # seconds between intermediate stdout DB flushes


def _safe_label(label: str) -> str:
    """Sanitise a label used in file paths — prevents path traversal."""
    cleaned = re.sub(r'[^a-zA-Z0-9._\-]', '_', label)
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


def _resolve_playbook_path(playbook_filename: str, db) -> Path:
    """Find which configured source directory contains this playbook file.

    Searches the builtin dir first, then all external sources in order.
    Returns the absolute path to the playbook file and the source directory.
    """
    from fleet_platform.models.platform_setting import PlatformSetting
    from fleet_platform.services.playbook_sources import get_all_playbook_dirs

    row = db.execute(
        select(PlatformSetting).where(PlatformSetting.key == "playbook_sources")
    ).scalar_one_or_none()
    sources_json = row.value if row else None

    all_dirs = get_all_playbook_dirs(sources_json, _DEFAULT_PLAYBOOKS_DIR)

    for d in all_dirs:
        candidate = d / playbook_filename
        if candidate.exists():
            return candidate, d

    # Fallback to builtin (will raise FileNotFoundError at ansible-runner time)
    return _DEFAULT_PLAYBOOKS_DIR / playbook_filename, _DEFAULT_PLAYBOOKS_DIR


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


def _flush_stdout(job_uuid: _uuid.UUID, lines: list[str], last_task: str | None) -> None:
    """Write accumulated stdout lines to DB mid-run so the UI can poll progress."""
    if not lines:
        return
    try:
        with get_sync_db() as db:
            job = db.execute(select(AnsibleJob).where(AnsibleJob.id == job_uuid)).scalar_one_or_none()
            if job:
                job.stdout = "\n".join(lines)
                if last_task:
                    # Append a progress indicator so the operator can see where we are
                    job.stdout += f"\n\n[running: {last_task}]"
                db.commit()
    except Exception as exc:
        _log.warning("playbook_tasks: failed to flush stdout for job %s: %s", job_uuid, exc)


@celery_app.task(
    name="fleet_platform.workers.playbook_tasks.run_playbook",
    bind=True,
    max_retries=0,
    queue="maintenance",
)
def run_playbook(self, job_id: str, ssh_username: str | None = None, ssh_password: str | None = None) -> dict:
    job_uuid = _uuid.UUID(job_id)
    stdout_lines: list[str] = []
    result = None

    try:
        with get_sync_db() as db:
            job = db.execute(select(AnsibleJob).where(AnsibleJob.id == job_uuid)).scalar_one_or_none()
            if not job:
                return {"status": "error", "reason": "job_not_found"}
            job.status = "running"
            job.started_at = datetime.now(UTC)
            db.commit()
            _, _settings_ssh_user, _settings_ssh_password, _ = _get_bootstrap_settings(db)
            ssh_user = ssh_username or _settings_ssh_user
            ssh_password = _settings_ssh_password if ssh_password is None else ssh_password

            # Resolve playbook path across all configured sources (not just builtin)
            playbook_path, playbooks_dir = _resolve_playbook_path(job.playbook, db)

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

        last_task: str | None = None
        last_db_write: float = time.time()

        with tempfile.TemporaryDirectory(prefix="kri-playbook-") as tmpdir:
            inv_path = _write_static_inventory(tmpdir, hosts)

            thread, runner = ansible_runner.run_async(
                private_data_dir=tmpdir,
                playbook=str(playbook_path),
                inventory=inv_path,
                extravars=job.extravars or {},
                envvars={
                    "ANSIBLE_USER": ssh_user,
                    "ANSIBLE_PASSWORD": ssh_password,
                    "ANSIBLE_COLLECTIONS_PATH": str(playbooks_dir / "collections" / "installed"),
                    # Reduce SSH timeout so stalled tasks surface faster
                    "ANSIBLE_TIMEOUT": "30",
                    "ANSIBLE_SSH_RETRIES": "2",
                },
                quiet=False,
                rotate_artifacts=1,
            )

            # Poll events from the running playbook and flush to DB every 30s.
            # runner.events re-reads ALL events from disk on every call, so we
            # track processed_count to only consume NEW events each iteration.
            processed_count = 0
            while thread.is_alive():
                all_events = list(runner.events)
                for event in all_events[processed_count:]:
                    event_type = event.get("event", "")
                    if event_type in ("runner_on_start", "playbook_on_task_start"):
                        task_name = event.get("event_data", {}).get("task", "")
                        if task_name:
                            last_task = task_name
                    msg = event.get("stdout", "")
                    if msg:
                        stdout_lines.append(msg)
                processed_count = len(all_events)

                now = time.time()
                if now - last_db_write >= _LOG_BATCH_INTERVAL:
                    _flush_stdout(job_uuid, stdout_lines, last_task)
                    last_db_write = now

                time.sleep(1)

            # Drain any remaining events the thread wrote after loop exited
            all_events = list(runner.events)
            for event in all_events[processed_count:]:
                msg = event.get("stdout", "")
                if msg:
                    stdout_lines.append(msg)

            result = runner.config.artifact_dir
            final_status = runner.status
            final_rc = runner.rc

        with get_sync_db() as db:
            job = db.execute(select(AnsibleJob).where(AnsibleJob.id == job_uuid)).scalar_one()
            job.status = "completed" if final_status == "successful" and final_rc == 0 else "failed"
            job.rc = final_rc
            job.stdout = "\n".join(stdout_lines) or f"rc={final_rc} status={final_status}"
            job.completed_at = datetime.now(UTC)
            db.commit()

        return {"status": final_status, "rc": final_rc, "job_id": job_id}

    except SoftTimeLimitExceeded:
        _log.warning("playbook_tasks: job %s hit soft time limit", job_uuid)
        _flush_stdout(job_uuid, stdout_lines, f"TIMED OUT after {_LOG_BATCH_INTERVAL}s idle")
        with get_sync_db() as db:
            job = db.execute(select(AnsibleJob).where(AnsibleJob.id == job_uuid)).scalar_one_or_none()
            if job and job.status == "running":
                job.status = "failed"
                job.stdout = (
                    ("\n".join(stdout_lines) + "\n\n" if stdout_lines else "")
                    + "[ERROR] Celery task time limit exceeded — playbook was terminated."
                )
                job.completed_at = datetime.now(UTC)
                db.commit()
        return {"status": "timeout", "job_id": job_id}

    except Exception as exc:
        _log.exception("playbook_tasks: unexpected error in job %s", job_uuid)
        with get_sync_db() as db:
            job = db.execute(select(AnsibleJob).where(AnsibleJob.id == job_uuid)).scalar_one_or_none()
            if job and job.status == "running":
                job.status = "failed"
                job.stdout = (
                    ("\n".join(stdout_lines) + "\n\n" if stdout_lines else "")
                    + f"[ERROR] {type(exc).__name__}: {exc}"
                )
                job.completed_at = datetime.now(UTC)
                db.commit()
        raise
