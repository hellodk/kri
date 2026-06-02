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
from fleet_platform.services.credential_resolver import resolve_node_credentials_sync
from fleet_platform.workers.celery_app import celery_app

_DEFAULT_PLAYBOOKS_DIR = Path(__file__).parent.parent.parent / "playbooks"

_log = logging.getLogger(__name__)
_SAFE_PATH_RE = re.compile(r'^[a-zA-Z0-9._\-]{1,128}$')
_LOG_BATCH_INTERVAL = 5  # seconds between intermediate stdout DB flushes


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


def _resolve_playbook_path(playbook_filename: str, db) -> tuple[Path, Path]:
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


_SOURCE_LABELS = {"node": "node override", "global": "global default", "manual": "manual override"}


def _source_label(source: str) -> str:
    # group sources keep their "group:<name>" form; others get a friendly label
    return _SOURCE_LABELS.get(source, source)


def _write_static_inventory(tmpdir: str, hosts: list[dict]) -> str:
    """Write a per-host inventory with each host's resolved SSH credentials.

    Credentials differ per host (node override vs group vs global), so they go
    inline per host rather than via a single global env var. Private keys are
    written to 0600 files in *tmpdir* and referenced, never inlined (#279).
    """
    # [targets] is the kri-managed group (referenced by kri-synthesized wrappers).
    # [all:children] makes all hosts visible to playbooks using `hosts: all`.
    lines = ["[targets]"]
    for h in hosts:
        parts = [h["hostname"], f"ansible_host={h['ip']}", f"ansible_user={h['ssh_user']}"]
        if h.get("auth_mode") == "key" and h.get("ssh_key"):
            key_path = Path(tmpdir) / f"{_safe_label(h['hostname'])}.key"
            key_path.write_text(h["ssh_key"] if h["ssh_key"].endswith("\n") else h["ssh_key"] + "\n")
            key_path.chmod(0o600)
            parts.append(f"ansible_ssh_private_key_file={key_path}")
        elif h.get("ssh_password"):
            parts.append(f"ansible_ssh_pass={h['ssh_password']}")
        lines.append(" ".join(parts))
    # Add [all:children] so playbooks using `hosts: all` see the selected nodes.
    # This fixes playbooks that use `hosts: all` instead of `hosts: targets`.
    lines += ["", "[all:children]", "targets"]
    inv_path = Path(tmpdir) / "inventory.ini"
    inv_path.write_text("\n".join(lines))
    inv_path.chmod(0o600)  # holds SSH passwords + IPs — never world/group readable
    return str(inv_path)


def _credential_source_banner(hosts: list[dict]) -> str:
    """Human-readable summary of where each host's credentials came from (#279)."""
    lines = ["Credentials resolved automatically (node → group → global):"]
    for h in hosts:
        lines.append(f"  {h['hostname']} ({h['ip']}) ← {_source_label(h['credential_source'])}")
    return "\n".join(lines)


def _write_var_file(path: Path, vars_dict: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_yaml.dump(vars_dict, default_flow_style=False, allow_unicode=True))


def _host_entry(node: Node, db, override: dict | None) -> dict:
    """Build a host inventory entry, resolving credentials per node (#279).

    *override* (an explicit ssh_user/ssh_password supplied via the API) wins
    over the resolver and is reported as source ``manual``.
    """
    if override and override.get("ssh_user"):
        creds = {
            "ssh_user": override["ssh_user"],
            "ssh_password": override.get("ssh_password") or "",
            "ssh_key": "",
            "auth_mode": "password",
            "credential_source": "manual",
        }
    else:
        creds = resolve_node_credentials_sync(node, db)
    return {
        "hostname": node.hostname or node.minion_id,
        "ip": node.ip_address,
        **creds,
    }


def _resolve_hosts(db, job: AnsibleJob, override: dict | None = None) -> list[dict] | None:
    if job.target_type == "node":
        node = db.execute(
            select(Node).where(Node.id == _uuid.UUID(job.target_id))
        ).scalar_one_or_none()
        if not node or not node.ip_address:
            return None
        return [_host_entry(node, db, override)]

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
        return [_host_entry(n, db, override) for n in nodes]

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
    soft_time_limit=600,   # 10 min soft limit → raises SoftTimeLimitExceeded
    time_limit=660,        # 11 min hard kill
)
def run_playbook(self, job_id: str, ssh_username: str | None = None, ssh_password: str | None = None, verbosity: int = 0) -> dict:
    job_uuid = _uuid.UUID(job_id)
    stdout_lines: list[str] = []

    try:
        with get_sync_db() as db:
            job = db.execute(select(AnsibleJob).where(AnsibleJob.id == job_uuid)).scalar_one_or_none()
            if not job:
                return {"status": "error", "reason": "job_not_found"}
            job.status = "running"
            job.started_at = datetime.now(UTC)
            db.commit()
            # Explicit per-call override (optional, e.g. via API). When absent,
            # credentials are auto-resolved per host (node → group → global).
            override = {"ssh_user": ssh_username, "ssh_password": ssh_password} if ssh_username else None

            # Resolve playbook path across all configured sources (not just builtin)
            playbook_path, playbooks_dir = _resolve_playbook_path(job.playbook, db)

        with get_sync_db() as db:
            job = db.execute(select(AnsibleJob).where(AnsibleJob.id == job_uuid)).scalar_one()
            hosts = _resolve_hosts(db, job, override)

        if not hosts:
            with get_sync_db() as db:
                job = db.execute(select(AnsibleJob).where(AnsibleJob.id == job_uuid)).scalar_one()
                job.status = "failed"
                job.stdout = "No hosts with IP addresses found for the selected target."
                job.completed_at = datetime.now(UTC)
                db.commit()
            return {"status": "error", "reason": "no_hosts"}

        # Tell the operator which credential source each host used (#279)
        banner = _credential_source_banner(hosts)
        stdout_lines.append(banner)
        stdout_lines.append("")
        with get_sync_db() as db:
            job = db.execute(select(AnsibleJob).where(AnsibleJob.id == job_uuid)).scalar_one()
            job.stdout = "\n".join(stdout_lines)
            db.commit()

        with get_sync_db() as db:
            job = db.execute(select(AnsibleJob).where(AnsibleJob.id == job_uuid)).scalar_one()
            if job.extravars:
                if job.target_type == "node" and hosts:
                    hostname = _safe_label(hosts[0]["hostname"])
                    vf = playbooks_dir / "host_vars" / f"{hostname}.yml"
                    _write_var_file(vf, job.extravars)
                elif job.target_type == "group":
                    vf = playbooks_dir / "group_vars" / f"{_safe_label(job.target_label)}.yml"
                    _write_var_file(vf, job.extravars)

        last_task: str | None = None
        last_db_write: float = time.time()
        job_start_time: float = time.time()

        with tempfile.TemporaryDirectory(prefix="kri-playbook-") as tmpdir:
            inv_path = _write_static_inventory(tmpdir, hosts)

            # If the selected item is a role directory (not a .yml file), synthesize
            # a minimal wrapper playbook so it can be executed by ansible-runner.
            if playbook_path.is_dir():
                role_name = playbook_path.name
                wrapper_path = Path(tmpdir) / f"_run_{_safe_label(role_name)}.yml"
                wrapper_path.write_text(
                    f"---\n- name: Apply role {role_name}\n"
                    f"  hosts: targets\n"
                    f"  gather_facts: true\n"
                    f"  roles:\n"
                    f"    - {role_name}\n"
                )
                _log.info("playbook_tasks: role %r → synthesized wrapper at %s", role_name, wrapper_path)
                playbook_path = wrapper_path

            thread, runner = ansible_runner.run_async(
                private_data_dir=tmpdir,
                playbook=str(playbook_path),
                inventory=inv_path,
                extravars=job.extravars or {},
                verbosity=max(0, min(4, verbosity or 0)),
                envvars={
                    # SSH credentials are set per host in the inventory (#279),
                    # resolved node → group → global — not via a single global env.
                    "ANSIBLE_COLLECTIONS_PATH": str(playbooks_dir / "collections" / "installed"),
                    # Point ansible at the source roles dir so role-only runs can find the role
                    "ANSIBLE_ROLES_PATH": str(playbooks_dir / "roles"),
                    # .ssh/ is mounted :ro — SSH cannot write to known_hosts.
                    # ANSIBLE_HOST_KEY_CHECKING=False sets StrictHostKeyChecking=no but
                    # OpenSSH still tries to RECORD new host keys in known_hosts, causing
                    # "Failed to add host to known_hosts" and connection close.
                    # Fix: route known_hosts writes to /dev/null via UserKnownHostsFile.
                    "ANSIBLE_HOST_KEY_CHECKING": "False",
                    # UserKnownHostsFile=/dev/null: .ssh is :ro, SSH can't write known_hosts
                    # StrictHostKeyChecking=no: skip host verification
                    # No ConnectionAttempts in SSH args — not supported as -o on all SSH versions.
                    # ANSIBLE_SSH_RETRIES=2 below handles retry at the Ansible level (3 total attempts).
                    "ANSIBLE_SSH_ARGS": "-o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no -o ControlMaster=no",
                    # SSH connection timeout per attempt
                    "ANSIBLE_TIMEOUT": "10",
                    # 2 retries = 3 total SSH attempts, then UNREACHABLE
                    "ANSIBLE_SSH_RETRIES": "2",
                    # Per-task execution timeout (catches stuck file copies, installs etc.)
                    "ANSIBLE_TASK_TIMEOUT": "300",
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
        elapsed = int(time.time() - job_start_time)
        _flush_stdout(job_uuid, stdout_lines, f"TIMED OUT after {elapsed}s elapsed")
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
