# fleet_platform/workers/ansible_tasks.py
"""Celery tasks for Ansible-based node bootstrap."""

import logging
import re
import secrets
import tempfile
import threading as _threading
import time
import uuid as _uuid
from datetime import UTC, datetime
from pathlib import Path

import ansible_runner
from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy import select

from fleet_platform.core.auth import hash_password
from fleet_platform.db.session import get_sync_db
from fleet_platform.models.bootstrap_run import BootstrapRun
from fleet_platform.models.node import Node
from fleet_platform.models.platform_setting import PlatformSetting
from fleet_platform.models.salt_master import SaltMaster
from fleet_platform.services.ssh_keypair import get_controller_pubkey
from fleet_platform.services.task_lock import unique_task
from fleet_platform.workers.celery_app import celery_app
from fleet_platform.workers.playbook_tasks import _append_capped

logger = logging.getLogger(__name__)

_PLAYBOOKS_DIR = Path(__file__).parent.parent.parent / "playbooks"
_DEFAULT_PILLAR_DIR = Path("/srv/salt/pillar")
_DEFAULT_KRI_DIR = Path.home() / ".kri"
_BOOTSTRAP_TIMEOUT_SECONDS = 600  # 10 minutes
_LOG_BATCH_INTERVAL = 5  # match run_playbook for live bootstrap logs (#544)
# Cap stored bootstrap stdout at 2 MB — same limit as playbook_tasks (#369).
_MAX_STDOUT_BYTES = 2 * 1024 * 1024
_TRUNCATION_SENTINEL = "\n\n[output truncated at 2 MB — full log not retained]"

_MINION_ID_RE = re.compile(r"^[a-zA-Z0-9._-]{1,128}$")


def _scrub_token(text: str, token: str) -> str:
    """Replace raw node token with *** in stdout to prevent accidental log exposure."""
    if not token or not text:
        return text
    return text.replace(token, "***")


def _validate_minion_id(minion_id: str) -> str:
    """Validate minion ID to prevent path traversal and YAML injection."""
    if not _MINION_ID_RE.match(minion_id):
        raise ValueError(f"Invalid minion ID '{minion_id}': must match [a-zA-Z0-9._-]{{1,128}}")
    return minion_id


def _get_bootstrap_settings(db) -> tuple[str, str, str, str]:
    """Returns (salt_master, ssh_user, ssh_password, controller_pubkey)."""
    from fleet_platform.services.platform_settings_svc import (
        CONTROLLER_PUBKEY_PATH,
        SALT_MASTER,
        SSH_PASSWORD,
        SSH_USERNAME,
        _fernet,
    )

    def _get(key: str) -> str:
        row = db.execute(select(PlatformSetting).where(PlatformSetting.key == key)).scalar_one_or_none()
        if row is None:
            return ""
        if row.is_encrypted and row.value:
            try:
                return _fernet().decrypt(row.value.encode()).decode()
            except Exception:
                logger.warning(
                    "_get_bootstrap_settings: cannot decrypt setting '%s' — "
                    "JWT_SECRET may have changed. Re-enter credentials in Settings → Bootstrap.",
                    key,
                )
                return ""
        return row.value or ""

    salt_master = _get(SALT_MASTER) or "localhost"
    ssh_user = _get(SSH_USERNAME) or "admin"
    ssh_password = _get(SSH_PASSWORD)
    pub_path = _get(CONTROLLER_PUBKEY_PATH) or str(_DEFAULT_KRI_DIR / "id_rsa.pub")
    pubkey = get_controller_pubkey(pub_path) or ""
    return salt_master, ssh_user, ssh_password, pubkey


def _get_node_credentials(node) -> tuple[str, str, str]:
    """Returns (ssh_user, ssh_password, ssh_auth_mode) from per-node stored credentials."""
    from fleet_platform.services.platform_settings_svc import decrypt_secret

    user = node.ssh_username or ""
    password = ""
    auth_mode = node.ssh_auth_mode or "password"
    if node.ssh_password_enc:
        try:
            password = decrypt_secret(node.ssh_password_enc)
        except Exception as e:
            logger.warning(
                "_get_node_credentials: failed to decrypt ssh_password_enc"
                " for node_id=%s — using empty password. Cause: %s",
                node.id,
                e,
            )
    return user, password, auth_mode


def _get_group_credentials(node, db) -> tuple[str, str, str, str]:
    """Return (ssh_user, ssh_password, ssh_key, auth_mode) from node's primary group.

    Primary group = alphabetically-first group the node belongs to that has credentials.
    Returns empty strings for all fields if no group credentials exist.
    """
    from fleet_platform.models.group import Group, GroupMember
    from fleet_platform.services.platform_settings_svc import decrypt_secret

    result = db.execute(
        select(Group)
        .join(GroupMember, GroupMember.group_id == Group.id)
        .where(GroupMember.node_id == node.id)
        .where(Group.ssh_username.isnot(None))
        .order_by(Group.name.asc())
        .limit(1)
    )
    group = result.scalar_one_or_none()
    if not group:
        return "", "", "", ""

    password = ""
    if group.ssh_password_enc:
        try:
            password = decrypt_secret(group.ssh_password_enc)
        except Exception:
            logger.warning(
                "_get_group_credentials: cannot decrypt ssh_password for group %s node %s",
                group.name,
                node.id,
            )

    ssh_key = ""
    if group.ssh_key_enc:
        try:
            ssh_key = decrypt_secret(group.ssh_key_enc)
        except Exception:
            logger.warning(
                "_get_group_credentials: cannot decrypt ssh_key for group %s node %s",
                group.name,
                node.id,
            )

    logger.info(
        "bootstrap_node: using group '%s' credentials for node %s (auth_mode=%s)",
        group.name,
        node.id,
        group.ssh_auth_mode,
    )
    return group.ssh_username or "", password, ssh_key, group.ssh_auth_mode or "password"


def _get_pillar_dir(db) -> Path:
    """Return the configured pillar directory, falling back to /srv/salt/pillar."""
    from sqlalchemy import select as _select

    from fleet_platform.models.platform_setting import PlatformSetting

    row = db.execute(_select(PlatformSetting).where(PlatformSetting.key == "pillar_dir")).scalar_one_or_none()
    if row and row.value:
        return Path(row.value)
    return _DEFAULT_PILLAR_DIR


@celery_app.task(
    name="fleet_platform.workers.ansible_tasks.bootstrap_node",
    bind=True,
    max_retries=0,
    queue="maintenance",
    acks_late=False,  # prevent double-bootstrap on SIGKILL (#444)
)
def bootstrap_node(
    self,
    node_id: str,
    target_ip: str,
    ssh_username: str | None = None,
    salt_master_ids: list[str] | None = None,
) -> dict:
    """Run bootstrap_mac_mini.yml against a single Mac Mini.

    salt_master_ids — optional list of SaltMaster UUIDs to use for this bootstrap.
    When None (default), all *enabled* SaltMaster rows are used (HA failover).
    An empty resolved list is a hard failure; an unreachable master is a warning only.
    """
    node_uuid = _uuid.UUID(node_id)
    logger.info("bootstrap_node starting: node_id=%s target_ip=%s", node_id, target_ip)

    # 1. Load node and mark as bootstrapping
    with get_sync_db() as db:
        node = db.execute(select(Node).where(Node.id == node_uuid)).scalar_one_or_none()
        if not node:
            return {"status": "error", "reason": "node_not_found"}
        try:
            _validate_minion_id(node.minion_id)
        except ValueError as e:
            node.bootstrap_status = "failed"
            node.bootstrap_error = str(e)
            db.commit()
            return {"status": "error", "reason": str(e)}

        node.bootstrap_status = "bootstrapping"
        node.bootstrap_ip = target_ip
        node.bootstrap_logs = ""  # clear any previous run's logs
        node.bootstrap_error = None
        db.commit()

        salt_master_settings, _settings_ssh_user, _settings_ssh_password, controller_pubkey = _get_bootstrap_settings(
            db
        )

        # A) Resolve the multi-master list (#534, epic #537).
        # If salt_master_ids given → load exactly those rows.
        # Otherwise → all enabled SaltMaster rows (HA: every master gets listed).
        master_objs: list[SaltMaster]
        if salt_master_ids:
            import uuid as _uuid_mod

            master_objs = list(
                db.execute(
                    select(SaltMaster).where(SaltMaster.id.in_([_uuid_mod.UUID(mid) for mid in salt_master_ids]))
                )
                .scalars()
                .all()
            )
        else:
            master_objs = list(db.execute(select(SaltMaster).where(SaltMaster.enabled.is_(True))).scalars().all())

        # Capture attributes while in-session (avoids DetachedInstanceError after commit)
        master_addresses: list[str] = [m.address for m in master_objs]
        master_statuses: dict[str, str] = {m.address: m.status for m in master_objs}
        master_names: dict[str, str] = {m.address: m.name for m in master_objs}
        # (#555) capture auto_accept + enough info for key.accept call after bootstrap
        master_auto_accept_info: list[dict] = [
            {"master": m, "auto_accept": getattr(m, "auto_accept", True), "name": m.name} for m in master_objs
        ]

        # Per-node stored credentials
        node_user, node_password, node_auth_mode = _get_node_credentials(node)

        # Group credentials: if no node-level creds, check primary group
        group_user, group_password, group_key, group_auth_mode = _get_group_credentials(node, db)

        # Priority: per-run args > node-stored > group-stored > global settings
        ssh_user = ssh_username or node_user or group_user or _settings_ssh_user or "admin"
        ssh_password = node_password or group_password or _settings_ssh_password

        # Resolve auth mode: per-run password/key arg takes priority,
        # then node-stored mode, then group mode
        if ssh_password:
            resolved_auth_mode = "password"
        elif node_user:
            resolved_auth_mode = node_auth_mode
        else:
            resolved_auth_mode = group_auth_mode or node_auth_mode

        # Load node's SSH key if key-auth mode is active and no per-run password provided
        node_ssh_key: str | None = group_key or None
        if resolved_auth_mode == "key" and node.ssh_key_enc:
            from fleet_platform.services.platform_settings_svc import decrypt_secret

            try:
                node_ssh_key = decrypt_secret(node.ssh_key_enc)
            except Exception:
                logger.warning("bootstrap_node: failed to decrypt ssh_key_enc for node_id=%s", node_id)

        if not ssh_password and not node_ssh_key:
            msg = (
                "SSH credentials are missing or could not be decrypted — "
                "the encryption key may have changed. "
                "Re-enter SSH credentials in Node → Secrets or Settings → Bootstrap, then retry."
            )
            logger.warning("bootstrap_node: %s node_id=%s", msg, node_id)
            node.bootstrap_status = "failed"
            node.bootstrap_error = msg
            db.commit()
            return {"status": "error", "reason": msg}

        # Capture node attributes before session closes (#462: prevent DetachedInstanceError)
        node_minion_id = node.minion_id
        node_ssh_host_key = node.ssh_host_key

    # B) Mandatory gate: no masters configured at all → hard fail.
    # This replaces the single-master mandatory check with multi-master awareness.
    if not master_addresses:
        _err = "No salt-master configured — add one in Settings → Salt Masters."
        logger.warning("bootstrap_node: %s node_id=%s", _err, node_id)
        with get_sync_db() as _fdb:
            _fn = _fdb.execute(select(Node).where(Node.id == node_uuid)).scalar_one_or_none()
            if _fn:
                _fn.bootstrap_status = "failed"
                _fn.bootstrap_error = _err
            # Finalise any running BootstrapRun (none yet at this stage, but guard anyway)
            _run = _fdb.execute(
                select(BootstrapRun)
                .where(BootstrapRun.node_id == node_uuid)
                .where(BootstrapRun.status == "running")
                .order_by(BootstrapRun.started_at.desc())
            ).scalar_one_or_none()
            if _run:
                _run.status = "failed"
                _run.finished_at = datetime.now(UTC)
                _run.error = _err
            _fdb.commit()
        return {"status": "error", "reason": _err}

    # C) Health warning (not a hard block): log unreachable masters but proceed (#534).
    unreachable = [addr for addr, st in master_statuses.items() if st == "unreachable"]
    if unreachable:
        _warn_names = [master_names.get(addr, addr) for addr in unreachable]
        logger.warning(
            "bootstrap_node: %d master(s) unreachable %r — proceeding with %d master(s) in HA list node_id=%s",
            len(unreachable),
            _warn_names,
            len(master_addresses),
            node_id,
        )

    # 2. Generate fresh node token — delivered to the minion via ansible-runner extravars
    # (node_token + ingest_url).  The local salt-pillar write was removed in #509:
    # the salt-master moved native to mm1 and the shared salt-pillar Docker volume no
    # longer exists.  Token delivery via extravars was always the correct path.
    raw_token = secrets.token_urlsafe(32)
    # Use the first master for the ingest URL (primary); others are HA failover only.
    first_master_address: str = master_addresses[0]
    ingest_url = f"http://{first_master_address}/api/v1/ingest"

    # 3. Update the stored token hash AND create a BootstrapRun record
    with get_sync_db() as db:
        node = db.execute(select(Node).where(Node.id == node_uuid)).scalar_one()
        node.node_token_hash = hash_password(raw_token)
        run = BootstrapRun(
            node_id=node_uuid,
            target_ip=target_ip,
            status="running",
            started_at=datetime.now(UTC),
        )
        db.add(run)
        db.commit()
        run_id = run.id

    # 4. Run Ansible with static inventory and capture stdout (streaming, #498)
    stdout_lines: list[str] = []
    _trunc_ref: dict = {"size": 0, "truncated": False}
    _last_task_ref: dict = {"task": ""}
    thread = None  # pre-initialise so SoftTimeLimitExceeded handler never NameErrors (#444)
    runner = None  # same reason
    bootstrap_error: str | None = None
    rc_display: int | str = "N/A"
    full_stdout: str = ""
    # node_minion_id and node_ssh_host_key captured inside first db session above (#462)
    last_db_write: float = time.time()
    _wrote_terminal_bootstrap = False  # sentinel: did step 6 complete? (#445 orphan guard)

    logger.info("bootstrap_node: starting ansible-runner for node_id=%s", node_id)

    try:
        with tempfile.TemporaryDirectory(prefix="kri-bootstrap-") as tmpdir:
            # Write SSH private key to temp file if using key auth
            key_file_path: str | None = None
            if node_ssh_key:
                key_path = Path(tmpdir) / "id_bootstrap"
                key_path.write_text(node_ssh_key)
                key_path.chmod(0o600)
                key_file_path = str(key_path)

            # Write static inventory — passwords are intentionally omitted from this file
            # to prevent plaintext credentials on disk.  They are passed via extravars
            # (which go through ansible-runner's env/extravars mechanism, not a temp file).
            inv_path = Path(tmpdir) / "inventory.ini"
            if key_file_path:
                inv_path.write_text(
                    f"[targets]\n"
                    f"{target_ip} ansible_host={target_ip} "
                    f"ansible_user={ssh_user} "
                    f"ansible_ssh_private_key_file={key_file_path}\n"
                )
            else:
                inv_path.write_text(f"[targets]\n{target_ip} ansible_host={target_ip} ansible_user={ssh_user}\n")
            inv_path.chmod(0o600)

            # TOFU: use node's stored host key for strict verification if available,
            # otherwise accept on first connection.
            import os as _os

            known_hosts_file: str | None = None
            if node_ssh_host_key:
                tmp_kh = tempfile.NamedTemporaryFile(mode="w", suffix=".known_hosts", delete=False)
                tmp_kh.write(f"{target_ip} {node_ssh_host_key}\n")
                tmp_kh.close()
                known_hosts_file = tmp_kh.name
                strict_check = f"-o StrictHostKeyChecking=yes -o UserKnownHostsFile={known_hosts_file}"
            else:
                strict_check = "-o StrictHostKeyChecking=accept-new"

            ssh_args = f"-F /dev/null {strict_check}"
            if key_file_path:
                ssh_args += f" -i {key_file_path}"

            # Passwords are passed via extravars so they never touch a file on disk.
            # ansible_ssh_pass / ansible_become_password are standard Ansible connection
            # variables; passing them here is equivalent to -e on the command line and
            # is handled entirely in memory by ansible-runner.
            password_extravars: dict[str, str] = {}
            if not key_file_path and ssh_password:
                password_extravars["ansible_ssh_pass"] = ssh_password
                password_extravars["ansible_become_password"] = ssh_password

            # C) Live log streaming via run_async + event_handler (#498).
            # ansible-runner's runner.events generator BLOCKS until the run finishes,
            # so polling it never streams mid-run.  run_async pushes events through
            # event_handler on the runner thread; the main loop flushes to the DB
            # every _LOG_BATCH_INTERVAL seconds so the UI sees logs grow live.
            _buf_lock = _threading.Lock()

            def _event_handler(event: dict) -> bool:
                et = event.get("event", "")
                if et in ("runner_on_start", "playbook_on_task_start"):
                    t = event.get("event_data", {}).get("task", "") or event.get("event_data", {}).get("task_path", "")
                    if t:
                        _last_task_ref["task"] = t
                msg = event.get("stdout", "")
                if msg:
                    with _buf_lock:
                        _append_capped(stdout_lines, msg, _trunc_ref)
                return True

            thread, runner = ansible_runner.run_async(
                private_data_dir=tmpdir,
                playbook=str(_PLAYBOOKS_DIR / "bootstrap_mac_mini.yml"),
                inventory=str(inv_path),
                extravars={
                    # Multi-master HA list (#534): playbook renders master: [list] + failover settings.
                    "salt_masters": master_addresses,
                    # Back-compat: single-value alias (first master) for any downstream that may
                    # still reference salt_master_address.
                    "salt_master_address": first_master_address,
                    "minion_id": node_minion_id,
                    "controller_pubkey": controller_pubkey,
                    "ingest_url": ingest_url,
                    "node_token": raw_token,
                    **password_extravars,
                },
                envvars={
                    "ANSIBLE_COLLECTIONS_PATH": str(_PLAYBOOKS_DIR / "collections" / "installed"),
                    # -F /dev/null skips ~/.ssh/config entirely — required when the config
                    # file is bind-mounted from the host with wrong ownership (UID mismatch
                    # between host user and container root causes "Bad owner or permissions")
                    "ANSIBLE_SSH_ARGS": ssh_args,
                    # Force ANSI colour codes into event["stdout"] even without a TTY (#498).
                    "ANSIBLE_FORCE_COLOR": "1",
                    # Unbuffered subprocess output → events stream without buffering delay.
                    "PYTHONUNBUFFERED": "1",
                },
                event_handler=_event_handler,
                quiet=True,  # DB is the sole sink — don't echo to worker stdout
                rotate_artifacts=0,  # 0 disables rotation (None causes TypeError in runner)
                timeout=_BOOTSTRAP_TIMEOUT_SECONDS,
            )

            # Non-blocking flush loop: event_handler fills stdout_lines on the runner
            # thread; the main thread snapshots + flushes to DB every _LOG_BATCH_INTERVAL
            # seconds so the UI streams mid-run (#498).  Does NOT touch runner.events.
            while thread.is_alive():
                now = time.time()
                if now - last_db_write >= _LOG_BATCH_INTERVAL:
                    with _buf_lock:
                        snapshot = list(stdout_lines)
                    last_task = _last_task_ref["task"]
                    joined = _scrub_token("\n".join(snapshot), raw_token)
                    with get_sync_db() as _db:
                        _n = _db.execute(select(Node).where(Node.id == node_uuid)).scalar_one_or_none()
                        _run = _db.execute(select(BootstrapRun).where(BootstrapRun.id == run_id)).scalar_one_or_none()
                        if _n:
                            _n.bootstrap_logs = joined
                            if _n.bootstrap_status == "bootstrapping" and last_task:
                                _n.bootstrap_error = f"[blocked at: TASK {last_task}]"
                        if _run:
                            _run.ansible_stdout = joined
                        _db.commit()
                    last_db_write = now
                time.sleep(1)
            thread.join()

            if known_hosts_file:
                try:
                    _os.unlink(known_hosts_file)
                except OSError:
                    pass

        # 5. Detect common failure modes from stdout
        full_stdout = "\n".join(stdout_lines)
        last_task = _last_task_ref["task"]
        # P3-2: guard rc=None so it never appears raw in error messages
        rc_display = runner.rc if runner is not None and runner.rc is not None else "N/A"
        final_status = runner.status if runner is not None else "error"

        if final_status == "timeout":
            bootstrap_error = (
                f"Timed out after 10 minutes. Last task: {last_task}" if last_task else "Timed out after 10 minutes."
            )
        elif final_status != "successful" or runner.rc != 0:
            if "UNREACHABLE" in full_stdout:
                bootstrap_error = f"SSH unreachable: check IP {target_ip} and SSH credentials in Settings"
            elif "Authentication failure" in full_stdout or "Permission denied" in full_stdout:
                bootstrap_error = "SSH auth failed: check SSH username/password in Settings → Bootstrap"
            elif "No such file or directory" in full_stdout and "salt" in full_stdout:
                bootstrap_error = "Salt package not found on target node"
            elif "Could not match supplied host pattern" in full_stdout:
                bootstrap_error = "Inventory misconfiguration — check minion ID format"
            else:
                bootstrap_error = f"ansible rc={rc_display} status={final_status}"

            logger.error(
                "bootstrap_node: ansible failure rc=%s status=%s last_task=%r node_id=%s",
                rc_display,
                final_status,
                last_task,
                node_id,
            )

        # 6. Update bootstrap status + logs; finalize the BootstrapRun record
        _bootstrap_succeeded = final_status == "successful" and runner is not None and runner.rc == 0
        with get_sync_db() as db:
            node = db.execute(select(Node).where(Node.id == node_uuid)).scalar_one()
            if _bootstrap_succeeded:
                node.bootstrap_status = "completed"
                node.bootstrap_error = None
            else:
                node.bootstrap_status = "failed"
                node.bootstrap_error = bootstrap_error
            node.bootstrap_logs = _scrub_token(full_stdout, raw_token) or f"rc={rc_display} status={final_status}"

            run_record: BootstrapRun | None = db.execute(
                select(BootstrapRun).where(BootstrapRun.id == run_id)
            ).scalar_one_or_none()
            if run_record:
                run_record.finished_at = datetime.now(UTC)
                run_record.status = "completed" if _bootstrap_succeeded else "failed"
                run_record.ansible_stdout = node.bootstrap_logs
                run_record.error = bootstrap_error

            db.commit()

        # 6a. (#555) Auto-accept minion key on each master that has auto_accept=True.
        # Runs only on successful bootstrap; never blocks or fails the overall task.
        if _bootstrap_succeeded:
            from fleet_platform.services.salt_api_client import SaltApiError, run_wheel

            auto_accept_notes: list[str] = []
            for info in master_auto_accept_info:
                if not info["auto_accept"]:
                    continue
                master_obj = info["master"]
                master_name = info["name"]
                try:
                    run_wheel(master_obj, "key.accept", match=node_minion_id)
                    note = f"minion key auto-accepted on {master_name}"
                    logger.info("bootstrap_node: %s node_id=%s minion_id=%s", note, node_id, node_minion_id)
                    auto_accept_notes.append(note)
                except SaltApiError as exc:
                    note = f"key auto-accept failed on {master_name}; accept manually ({exc.reason})"
                    logger.warning(
                        "bootstrap_node: salt-api key.accept failed master=%s node_id=%s: %s",
                        master_name,
                        node_id,
                        exc.reason,
                    )
                    auto_accept_notes.append(note)
                except Exception as exc:  # noqa: BLE001
                    note = f"key auto-accept failed on {master_name}; accept manually ({exc})"
                    logger.warning(
                        "bootstrap_node: key.accept unexpected error master=%s node_id=%s: %s",
                        master_name,
                        node_id,
                        exc,
                    )
                    auto_accept_notes.append(note)

            if auto_accept_notes:
                extra = "\n".join(f"[kri] {n}" for n in auto_accept_notes)
                with get_sync_db() as db:
                    _n = db.execute(select(Node).where(Node.id == node_uuid)).scalar_one_or_none()
                    if _n:
                        _n.bootstrap_logs = (_n.bootstrap_logs or "") + "\n" + extra
                    _run2 = db.execute(select(BootstrapRun).where(BootstrapRun.id == run_id)).scalar_one_or_none()
                    if _run2:
                        _run2.ansible_stdout = (_run2.ansible_stdout or "") + "\n" + extra
                    db.commit()

        _wrote_terminal_bootstrap = True

    except SoftTimeLimitExceeded:
        # #444: Celery soft time limit hit — mark node failed, re-raise so Celery handles cleanup.
        # The finally block below handles the BootstrapRun orphan (#445 Part A).
        logger.warning("bootstrap_node: soft time limit exceeded for node_id=%s", node_id)
        with get_sync_db() as db:
            _n = db.execute(select(Node).where(Node.id == node_uuid)).scalar_one_or_none()
            if _n and _n.bootstrap_status == "bootstrapping":
                _n.bootstrap_status = "failed"
                _n.bootstrap_error = "Celery task soft time limit exceeded — bootstrap was terminated."
            db.commit()
        raise

    except Exception as _exc:
        # #509: any unhandled exception (e.g. ansible-runner internal error, unexpected
        # OSError) must not leave the node stuck at 'bootstrapping'.  Record a terminal
        # status so the UI reflects the failure and operators can retry.
        _err_msg = f"Unexpected error during bootstrap: {type(_exc).__name__}: {_exc}"
        logger.exception("bootstrap_node: unhandled exception for node_id=%s", node_id)
        with get_sync_db() as db:
            _n = db.execute(select(Node).where(Node.id == node_uuid)).scalar_one_or_none()
            if _n and _n.bootstrap_status == "bootstrapping":
                _n.bootstrap_status = "failed"
                _n.bootstrap_error = _err_msg
            db.commit()
        # Re-raise so Celery marks the task as FAILURE; the finally block finalises BootstrapRun.
        raise

    finally:
        # #445 Part A / #509: if step 6 never completed (SoftTimeLimitExceeded or other
        # exception), mark any still-running BootstrapRun row as failed so it is not left
        # as an orphan.
        if not _wrote_terminal_bootstrap:
            with get_sync_db() as db:
                _run = db.execute(
                    select(BootstrapRun)
                    .where(BootstrapRun.node_id == node_uuid)
                    .where(BootstrapRun.status == "running")
                    .order_by(BootstrapRun.started_at.desc())
                ).scalar_one_or_none()
                if _run:
                    _run.status = "failed"
                    _run.finished_at = datetime.now(UTC)
                db.commit()

    return {"status": runner.status if runner is not None else "error", "rc": rc_display, "node_id": node_id}


@celery_app.task(
    name="fleet_platform.workers.ansible_tasks.collect_node_grains",
    bind=True,
    max_retries=0,
    queue="maintenance",
)
def collect_node_grains(self, node_id: str) -> dict:
    """SSH into node via controller key, run salt-call grains, push to ingest API."""
    import json as _json
    import subprocess

    node_uuid = _uuid.UUID(node_id)
    with get_sync_db() as db:
        node = db.execute(select(Node).where(Node.id == node_uuid)).scalar_one_or_none()
        if not node:
            return {"status": "error", "reason": "node_not_found"}

        target_ip = node.bootstrap_ip
        salt_master, _, _, _ = _get_bootstrap_settings(db)
        node_user, node_password, node_auth_mode = _get_node_credentials(node)
        ssh_user = node_user or "admin"
        minion_id = node.minion_id
        pillar_dir = _get_pillar_dir(db)

        # Prefer kri_api_url for ingest; fall back to salt_master
        from fleet_platform.services.platform_settings_svc import KRI_API_URL

        kri_api_url = ""
        try:
            row = db.execute(select(PlatformSetting).where(PlatformSetting.key == KRI_API_URL)).scalar_one_or_none()
            if row and row.value:
                kri_api_url = row.value.rstrip("/")
        except Exception:
            pass

    ingest_base = kri_api_url or (f"http://{salt_master}" if salt_master else "http://localhost")
    ingest_url = f"{ingest_base}/api/v1/ingest"

    # Controller private key — deployed to every bootstrapped node
    # Must be copied to a tmp file so SSH doesn't reject it for wrong ownership
    # (the ~/.kri volume is mounted from host uid != container uid)
    controller_priv = Path.home() / ".kri" / "id_rsa"

    with tempfile.TemporaryDirectory(prefix="kri-grains-") as tmpdir:
        key_file_path: str | None = None
        if controller_priv.exists():
            tmp_key = Path(tmpdir) / "id_ctrl"
            tmp_key.write_bytes(controller_priv.read_bytes())
            tmp_key.chmod(0o600)
            key_file_path = str(tmp_key)

        # TOFU: use node's stored host key for strict verification if available,
        # otherwise accept on first connection.
        import os as _os2

        grains_known_hosts_file: str | None = None
        if node.ssh_host_key:
            tmp_kh2 = tempfile.NamedTemporaryFile(mode="w", suffix=".known_hosts", delete=False)
            tmp_kh2.write(f"{target_ip} {node.ssh_host_key}\n")
            tmp_kh2.close()
            grains_known_hosts_file = tmp_kh2.name
            grains_strict_opts = [
                "-o",
                "StrictHostKeyChecking=yes",
                "-o",
                f"UserKnownHostsFile={grains_known_hosts_file}",
            ]
        else:
            grains_strict_opts = ["-o", "StrictHostKeyChecking=accept-new"]

        ssh_opts = [
            "ssh",
            "-F",
            "/dev/null",  # skip mounted ~/.ssh/config (UID mismatch in container)
            *grains_strict_opts,
            "-o",
            "ConnectTimeout=15",
            "-o",
            "BatchMode=yes",
        ]
        if key_file_path:
            ssh_opts += ["-i", key_file_path]

        ssh_cmd = ssh_opts + [
            f"{ssh_user}@{target_ip}",
            (
                "sudo /opt/homebrew/bin/salt-call --local grains.items --out=json --log-level=warning 2>/dev/null"
                " || sudo /usr/local/bin/salt-call --local grains.items --out=json --log-level=warning 2>/dev/null"
            ),
        ]

        try:
            proc = subprocess.run(ssh_cmd, capture_output=True, text=True, timeout=30)
            if proc.returncode != 0:
                return {"status": "error", "reason": f"ssh failed: {proc.stderr[:200]}"}

            raw = proc.stdout.strip()
            parsed = _json.loads(raw)
            grains = parsed.get("local", parsed)

            # Read node token from pillar file
            pillar_file = pillar_dir / f"{minion_id}.sls"
            node_token = ""
            if pillar_file.exists():
                for line in pillar_file.read_text().splitlines():
                    if "node_token:" in line:
                        node_token = line.split("node_token:")[-1].strip()
                        break

            if not node_token:
                return {"status": "error", "reason": "no node_token found in pillar"}

            import urllib.request

            payload = _json.dumps({"minion_id": minion_id, "grains": grains}).encode()
            req = urllib.request.Request(
                f"{ingest_url}/grains",
                data=payload,
                headers={"Content-Type": "application/json", "X-Node-Token": node_token},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=15) as resp:  # nosec B310
                return {"status": "ok", "http_status": resp.status, "node_id": node_id}

        except subprocess.TimeoutExpired:
            return {"status": "error", "reason": "ssh timeout"}
        except SoftTimeLimitExceeded:
            logger.warning("grain collection timed out for node %s", node_id)
            raise
        except Exception as e:
            return {"status": "error", "reason": str(e)[:200]}
        finally:
            if grains_known_hosts_file:
                try:
                    _os2.unlink(grains_known_hosts_file)
                except OSError:
                    pass


@celery_app.task(
    name="fleet_platform.workers.ansible_tasks.refresh_all_node_grains",
    queue="maintenance",
)
@unique_task()  # singleton — one run at a time; must be inner decorator so .delay is preserved
def refresh_all_node_grains() -> dict:
    """Periodic: trigger grain collection for all bootstrapped online nodes."""
    try:
        with get_sync_db() as db:
            rows = db.execute(select(Node).where(Node.bootstrap_status == "completed")).scalars().all()
            node_ids = [str(n.id) for n in rows if n.bootstrap_ip]

        for nid in node_ids:
            collect_node_grains.delay(nid)

        return {"queued": len(node_ids)}
    except SoftTimeLimitExceeded:
        logger.warning("grain collection timed out for node refresh_all_node_grains")
        raise
