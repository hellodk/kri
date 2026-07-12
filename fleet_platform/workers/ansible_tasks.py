# fleet_platform/workers/ansible_tasks.py
"""Celery tasks for Ansible-based node bootstrap."""

import logging
import secrets
import tempfile
import threading as _threading
import time
import uuid as _uuid
from datetime import UTC, datetime
from pathlib import Path

import ansible_runner
from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy import func, select

from fleet_platform.core.auth import hash_password
from fleet_platform.db.session import get_sync_db
from fleet_platform.models.bootstrap_run import BootstrapRun
from fleet_platform.models.master_provision_run import MasterProvisionRun
from fleet_platform.models.node import Node
from fleet_platform.models.platform_setting import PlatformSetting
from fleet_platform.models.salt_master import SaltMaster
from fleet_platform.services.credential_resolver import resolve_node_credentials_sync
from fleet_platform.services.grains_collector import _grains_via_salt_api, _grains_via_ssh
from fleet_platform.services.job_events import publish_job_event
from fleet_platform.services.node_credentials import (
    _get_bootstrap_settings,
    _resolve_node_master_creds,
)
from fleet_platform.services.ssh_host_key_svc import to_known_hosts_token
from fleet_platform.services.task_lock import unique_task
from fleet_platform.workers.ansible_helpers import (
    _detect_os_family,
    _get_pillar_dir,  # noqa: F401 — re-exported for test patch targets (#509 removed its call site)
    _scrub_token,
    _validate_minion_id,
)
from fleet_platform.workers.celery_app import celery_app
from fleet_platform.workers.playbook_tasks import _append_capped

logger = logging.getLogger(__name__)

_PLAYBOOKS_DIR = Path(__file__).parent.parent.parent / "playbooks"
_DEFAULT_KRI_DIR = Path.home() / ".kri"
_BOOTSTRAP_TIMEOUT_SECONDS = 600  # 10 minutes
_LOG_BATCH_INTERVAL = 5  # match run_playbook for live bootstrap logs (#544)
# Cap stored bootstrap stdout at 2 MB — same limit as playbook_tasks (#369).
_MAX_STDOUT_BYTES = 2 * 1024 * 1024
_TRUNCATION_SENTINEL = "\n\n[output truncated at 2 MB — full log not retained]"


def _mask_extravar(key: str, value: object) -> str:
    """Render an extravar value for display, masking secrets (#960).

    Any key hinting at a credential (pass/password/token/secret/credential, or
    ending in _key) is redacted to ****; long non-secret values are truncated.
    """
    kl = key.lower()
    if any(h in kl for h in ("pass", "token", "secret", "credential")) or kl.endswith("_key"):
        return "****"
    s = str(value)
    return s if len(s) <= 120 else s[:117] + "..."


def _format_ansible_cmdline(playbook: str, inventory: str, extravars: dict) -> str:
    """Build the reproducible ansible-playbook command line for the log header.

    Secrets are masked via _mask_extravar. Emitted at the top of the bootstrap /
    provision output so operators see the exact effective invocation (#960).
    """
    parts = ["ansible-playbook", "-i", inventory, playbook]
    for k, v in extravars.items():
        parts.append("-e")
        parts.append(f"{k}={_mask_extravar(k, v)}")
    cmd = " ".join(parts)
    return f"── Ansible command ──────────────────────────────────────────\n$ {cmd}\n──────────────────────────────────────────────────────────────\n"


def _classify_ansible_failure_category(full_stdout: str) -> str | None:
    """Categorize an ansible failure from its stdout for human error messages.

    Order matters: the salt-master reachability gate (host_prep_gate.yml) prints
    the word "UNREACHABLE" in *debug* lines even though SSH itself succeeded, so
    it must be checked BEFORE the SSH-unreachable marker. Real SSH-unreachable is
    Ansible's host marker "UNREACHABLE!" (with the exclamation) or "unreachable=1"
    in the PLAY RECAP — never the bare word (#992). Returns None when none match
    so the caller keeps its own rc/status default.
    """
    if "Target cannot reach any salt-master" in full_stdout:
        return "salt_master_gate"
    if "Authentication failure" in full_stdout or "Permission denied" in full_stdout:
        return "ssh_auth"
    if "UNREACHABLE!" in full_stdout or "unreachable=1" in full_stdout:
        return "ssh_unreachable"
    return None


@celery_app.task(
    name="fleet_platform.workers.ansible_tasks.bootstrap_node",
    bind=True,
    max_retries=0,
    queue="ansible",  # dedicated long-job queue — isolates from control plane (#579)
    acks_late=False,  # prevent double-bootstrap on SIGKILL (#444)
)
def bootstrap_node(
    self,
    node_id: str,
    target_ip: str,
    ssh_username: str | None = None,
    salt_master_ids: list[str] | None = None,
    node_exporter_version: str | None = None,
    node_exporter_listen_address: str | None = None,
    node_exporter_url_override: str | None = None,
    as_master: bool = False,
) -> dict:
    """Run bootstrap_node.yml against a fleet node (macOS or Linux).

    salt_master_ids — optional list of SaltMaster UUIDs to use for this bootstrap.
    When None (default), all *enabled* SaltMaster rows are used (HA failover).
    An empty resolved list is a hard failure; an unreachable master is a warning only.

    as_master — Phase A master-promotion (#980). When True and the bootstrap
    succeeds, this node is auto-registered as a SaltMaster and provisioning is
    enqueued (mirrors ``promote_node_to_master`` in salt_masters.py, but
    synchronous). Never fails the overall bootstrap on error.
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
        publish_job_event("bootstrap", node_id, "running")

        *_, controller_pubkey = _get_bootstrap_settings(db)

        # OTLP push settings (#968) — read while the db session is open, injected
        # below as extravars so the otel_collector role targets the operator-
        # configured endpoint instead of its placeholder default. Unset settings
        # are omitted so the role's defaults apply.
        from fleet_platform.services.platform_settings_svc import get_setting_sync

        _otlp_endpoint = get_setting_sync(db, "otlp_endpoint")
        _otlp_protocol = get_setting_sync(db, "otlp_protocol")
        _otlp_headers = get_setting_sync(db, "otlp_headers")

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

        # Resolve SSH credentials via the group-only credential resolver (#989).
        # Chain: credential_groups (group membership) → controller key → none.
        # Per-run ssh_username argument still takes priority over the resolved user.
        resolved_creds = resolve_node_credentials_sync(node, db)
        ssh_user = ssh_username or resolved_creds["ssh_user"] or "admin"
        ssh_password = resolved_creds["ssh_password"]
        node_ssh_key: str | None = resolved_creds["ssh_key"] or None

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
                _kh_token = to_known_hosts_token(node_ssh_host_key)
                if _kh_token:
                    tmp_kh = tempfile.NamedTemporaryFile(mode="w", suffix=".known_hosts", delete=False)
                    tmp_kh.write(f"{target_ip} {_kh_token}\n")
                    tmp_kh.close()
                    known_hosts_file = tmp_kh.name
                    strict_check = f"-o StrictHostKeyChecking=yes -o UserKnownHostsFile={known_hosts_file}"
                else:
                    # Stored key cannot be normalised to a valid token; fall
                    # back so bootstrap is not hard-blocked (#840).
                    strict_check = "-o StrictHostKeyChecking=accept-new"
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

            # Build runtime-override extravars for #830.
            # Only inject when the caller provided a value — omitted vars fall back
            # to playbook/group_vars defaults (extravars always win in Ansible precedence).
            runtime_extravars: dict = {}
            if node_exporter_version is not None:
                runtime_extravars["node_exporter_version"] = node_exporter_version
            if node_exporter_listen_address is not None:
                runtime_extravars["node_exporter_listen_address"] = node_exporter_listen_address
            if node_exporter_url_override is not None:
                runtime_extravars["node_exporter_url_override"] = node_exporter_url_override
            # OTLP push target for the otel_collector role (#968).
            if _otlp_endpoint:
                runtime_extravars["otlp_endpoint"] = _otlp_endpoint
            if _otlp_protocol:
                runtime_extravars["otlp_protocol"] = _otlp_protocol
            if _otlp_headers:
                runtime_extravars["otlp_headers"] = _otlp_headers

            _bootstrap_playbook = str(_PLAYBOOKS_DIR / "bootstrap_node.yml")
            _extravars = {
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
                **runtime_extravars,
            }
            # Emit the full effective command (secrets masked) at the top of the log (#960).
            _append_capped(stdout_lines, _format_ansible_cmdline(_bootstrap_playbook, str(inv_path), _extravars), _trunc_ref)

            thread, runner = ansible_runner.run_async(
                private_data_dir=tmpdir,
                playbook=_bootstrap_playbook,
                inventory=str(inv_path),
                extravars=_extravars,
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
            _cat = _classify_ansible_failure_category(full_stdout)
            if _cat == "salt_master_gate":
                bootstrap_error = (
                    "SSH reached the node, but it cannot reach the salt-master on "
                    "4505/4506 — check the master is running and reachable from this node"
                )
            elif _cat == "ssh_auth":
                bootstrap_error = "SSH auth failed: check SSH username/password in Settings → Bootstrap"
            elif _cat == "ssh_unreachable":
                bootstrap_error = f"SSH unreachable: check IP {target_ip} and SSH credentials in Settings"
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
            publish_job_event("bootstrap", node_id, node.bootstrap_status)

            # Capture while still in-session (avoids DetachedInstanceError once this
            # `with` block closes) — needed by the as_master registration below (#980).
            _node_bootstrap_ip = node.bootstrap_ip
            _node_hostname = node.hostname

        # 6a2. (#980) Phase A: auto-register + provision this node as a salt-master
        # when the bootstrap request opted in with as_master=True. Mirrors
        # promote_node_to_master (fleet_platform/api/routes/salt_masters.py) but
        # synchronous, and always swallows errors so a master-registration hiccup
        # never fails the (already-successful) bootstrap.
        if _bootstrap_succeeded and as_master:
            try:
                with get_sync_db() as db:
                    existing_master = db.execute(
                        select(SaltMaster).where(SaltMaster.node_id == node_uuid)
                    ).scalar_one_or_none()
                    if existing_master is not None:
                        logger.info(
                            "bootstrap_node: as_master requested but a SaltMaster already exists "
                            "for node_id=%s master_id=%s — skipping",
                            node_id,
                            existing_master.id,
                        )
                    elif not _node_bootstrap_ip:
                        logger.warning(
                            "bootstrap_node: as_master requested but node has no bootstrap_ip node_id=%s",
                            node_id,
                        )
                    else:
                        base_name = (_node_hostname or node_minion_id)[:255]
                        candidate_name = base_name
                        suffix = 1
                        while True:
                            conflict = db.execute(
                                select(SaltMaster).where(SaltMaster.name == candidate_name)
                            ).scalar_one_or_none()
                            if conflict is None:
                                break
                            candidate_name = f"{base_name}-{suffix}"[:255]
                            suffix += 1

                        is_first = db.execute(select(func.count()).select_from(SaltMaster)).scalar_one() == 0

                        new_master = SaltMaster(
                            name=candidate_name,
                            address=_node_bootstrap_ip,
                            enabled=True,
                            is_default=is_first,
                            api_url=f"https://{_node_bootstrap_ip}:4507",
                            api_eauth="pam",
                            provision_status="provisioning",
                            node_id=node_uuid,
                        )
                        db.add(new_master)
                        db.commit()
                        db.refresh(new_master)

                        from fleet_platform.workers.celery_app import celery_app

                        celery_app.send_task(
                            "fleet_platform.workers.ansible_tasks.provision_master",
                            args=[str(new_master.id), "install"],
                            queue="ansible",
                        )
                        logger.info(
                            "bootstrap_node: as_master registered node_id=%s as SaltMaster "
                            "master_id=%s name=%s — provisioning enqueued",
                            node_id,
                            new_master.id,
                            candidate_name,
                        )
            except Exception:
                logger.exception(
                    "bootstrap_node: as_master registration/provisioning failed node_id=%s", node_id
                )

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
    """Collect a node's grains and push them to the ingest API.

    Primary path (#708): fetch grains over salt-api (``grains.items`` via the
    local client) using the node's master — no SSH and no controller key, so it
    works for every connected minion regardless of the worker container's uid.
    Falls back to SSH ``salt-call --local`` only when the minion can't be
    reached through its master (e.g. key not yet accepted).
    """
    import json as _json

    node_uuid = _uuid.UUID(node_id)
    with get_sync_db() as db:
        node = db.execute(select(Node).where(Node.id == node_uuid)).scalar_one_or_none()
        if not node:
            return {"status": "error", "reason": "node_not_found"}

        target_ip = node.bootstrap_ip
        resolved_creds = resolve_node_credentials_sync(node, db)
        ssh_user = resolved_creds["ssh_user"] or "admin"
        minion_id = node.minion_id
        ssh_host_key = node.ssh_host_key
        master_creds = _resolve_node_master_creds(db, node)

        # Prefer kri_api_url for ingest; no salt_master address fallback (#562)
        from fleet_platform.services.platform_settings_svc import KRI_API_URL

        kri_api_url = ""
        try:
            row = db.execute(select(PlatformSetting).where(PlatformSetting.key == KRI_API_URL)).scalar_one_or_none()
            if row and row.value:
                kri_api_url = row.value.rstrip("/")
        except Exception:
            pass

        # Mint a fresh node token for this grain-collection run (#739).
        # The salt-pillar write was removed in #509 so the pillar file never
        # exists; the token now lives as a bcrypt hash on node.node_token_hash.
        raw_token = secrets.token_urlsafe(32)
        node.node_token_hash = hash_password(raw_token)
        db.commit()

    ingest_base = kri_api_url or "http://localhost"
    ingest_url = f"{ingest_base}/api/v1/ingest"

    # 1) Primary: salt-api grains.items (no SSH, no controller key) — #708
    grains: dict | None = None
    via = ""
    failures: list[str] = []
    if master_creds and master_creds.get("api_url"):
        grains, reason = _grains_via_salt_api(master_creds, minion_id)
        if grains is not None:
            via = "salt-api"
        elif reason:
            failures.append(f"salt-api: {reason}")
    else:
        failures.append("salt-api: node has no enabled master configured")

    # 2) Fallback: SSH salt-call --local (legacy; requires controller key)
    if grains is None:
        try:
            grains, reason = _grains_via_ssh(target_ip, ssh_user, minion_id, ssh_host_key)
            if grains is not None:
                via = "ssh"
            elif reason:
                failures.append(f"ssh: {reason}")
        except SoftTimeLimitExceeded:
            logger.warning("collect_node_grains: soft time limit exceeded for node_id=%s — clean exit", node_id)
            return {"status": "timeout", "node_id": node_id}

    if grains is None:
        return {"status": "error", "reason": "; ".join(failures) or "grain collection failed"}

    # 3) Push grains to ingest using the freshly minted node token (#739).
    # raw_token was generated and its hash persisted to node.node_token_hash above.
    try:
        import urllib.request

        payload = _json.dumps({"minion_id": minion_id, "grains": grains}).encode()
        req = urllib.request.Request(
            f"{ingest_url}/grains",
            data=payload,
            headers={"Content-Type": "application/json", "X-Node-Token": raw_token},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:  # nosec B310
            return {"status": "ok", "http_status": resp.status, "node_id": node_id, "via": via}
    except SoftTimeLimitExceeded:
        logger.warning("collect_node_grains: soft time limit exceeded for node_id=%s — clean exit", node_id)
        return {"status": "timeout", "node_id": node_id}
    except Exception as e:
        return {"status": "error", "reason": str(e)[:200]}


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
        # Log + clean exit — no DB status to update for grain tasks (#471)
        logger.warning("refresh_all_node_grains: soft time limit exceeded — clean exit")
        return {"queued": 0, "status": "timeout"}


# ---------------------------------------------------------------------------
# provision_master — install/reconfigure salt-master on a host (#557)
# ---------------------------------------------------------------------------

_PROVISION_TIMEOUT_SECONDS = 1200  # 1200 s (twice the bootstrap) — salt-master install is heavier

# Playbook filenames; keys are canonical os_family values
_MASTER_PLAYBOOKS: dict[str, str] = {
    "Darwin": "install_salt_master.yml",
    "Linux": "install_salt_master_linux.yml",
}
_DEFAULT_OS_FAMILY = "Linux"


def _resolve_master_ssh_creds(master, db) -> dict:
    """Resolve SSH creds for provisioning a salt-master (#965).

    Mirrors bootstrap_node's FK-aware chain: per-master creds on the SaltMaster
    row → the linked node's resolved credentials (when the master was promoted
    from a node, ``master.node_id`` set) → global bootstrap settings. Never
    silently defaults the user to 'admin' — an unresolvable user yields '' so the
    caller fails with a clear message instead of SSHing as the wrong user.
    """
    from fleet_platform.services.platform_settings_svc import decrypt_secret

    global_user, global_password, _pub = _get_bootstrap_settings(db)

    # 1. Per-master explicit creds (decrypt whatever is stored on the row).
    master_key: str | None = None
    if master.ssh_key_enc:
        try:
            master_key = decrypt_secret(master.ssh_key_enc)
        except Exception as _e:  # pragma: no cover - defensive
            logger.warning("_resolve_master_ssh_creds: cannot decrypt ssh_key_enc: %s", _e)
    master_password: str | None = None
    if master.ssh_password_enc:
        try:
            master_password = decrypt_secret(master.ssh_password_enc)
        except Exception as _e:  # pragma: no cover - defensive
            logger.warning("_resolve_master_ssh_creds: cannot decrypt ssh_password_enc: %s", _e)

    # 2. Linked-node resolved creds (promoted-from-node case).
    node_creds: dict = {}
    if master.node_id:
        node = db.execute(select(Node).where(Node.id == master.node_id)).scalar_one_or_none()
        if node is not None:
            node_creds = resolve_node_credentials_sync(node, db) or {}

    # Priority: per-master > linked node > global. No 'admin' default.
    ssh_user = master.ssh_user or node_creds.get("ssh_user") or global_user or ""
    ssh_key = master_key or (node_creds.get("ssh_key") or None)
    ssh_password = master_password or (node_creds.get("ssh_password") or None)
    # Global password is the last resort, only when nothing else supplied a secret.
    if not ssh_key and not ssh_password:
        ssh_password = global_password

    return {"ssh_user": ssh_user, "ssh_password": ssh_password, "ssh_key": ssh_key}


def _ensure_master_api_creds(master) -> str:
    """Return the master's salt-api password, generating + persisting creds on the
    record when absent (#976).

    provision passes this password to api_user.yml, which creates the ``krisalt``
    PAM user with it, and kri's salt_api_client later authenticates with the same
    stored password. A master promoted from a node (or created without api creds)
    has no password — without this it would be provisioned with an EMPTY password
    and every salt-api call would 401 (degrading the Minion Keys page + the
    pending-count notification badge to empty). The caller commits the session.
    """
    from fleet_platform.services.platform_settings_svc import decrypt_secret, encrypt_secret

    api_password = ""
    if master.api_password_enc:
        try:
            api_password = decrypt_secret(master.api_password_enc)
        except Exception as _e:  # pragma: no cover - defensive
            logger.warning("_ensure_master_api_creds: cannot decrypt api_password_enc: %s", _e)

    if not api_password:
        import secrets as _secrets

        api_password = _secrets.token_urlsafe(24)
        master.api_password_enc = encrypt_secret(api_password)
    if not master.api_user:
        master.api_user = "krisalt"
    return api_password


@celery_app.task(
    name="fleet_platform.workers.ansible_tasks.provision_master",
    bind=True,
    max_retries=0,
    queue="ansible",  # dedicated long-job queue — isolates from control plane (#579)
    acks_late=False,
)
def provision_master(self, salt_master_id: str, action: str = "install") -> dict:
    """Install or reconfigure salt-master + salt-api on a host.

    Mirrors bootstrap_node's ansible_runner.run_async + event_handler streaming
    pattern (#557, master-lifecycle epic).

    The salt-master role is idempotent; action='reconfigure' is identical to
    action='install' at playbook level — no special-casing needed.
    """
    from fleet_platform.services.salt_master_probe import run_probe

    master_uuid = _uuid.UUID(salt_master_id)
    logger.info("provision_master starting: salt_master_id=%s action=%s", salt_master_id, action)

    # ------------------------------------------------------------------
    # 1. Load SaltMaster row + resolve SSH credentials
    # ------------------------------------------------------------------
    with get_sync_db() as db:
        master = db.execute(select(SaltMaster).where(SaltMaster.id == master_uuid)).scalar_one_or_none()
        if not master:
            return {"status": "error", "reason": "master_not_found"}

        # Resolve SSH host
        ssh_host: str = master.ssh_host or master.address

        # Resolve SSH creds via the FK-aware chain (per-master > linked node >
        # global). A master promoted from a node inherits that node's working
        # credentials; no silent 'admin' default. (#965)
        _master_creds = _resolve_master_ssh_creds(master, db)
        ssh_user = _master_creds["ssh_user"]
        ssh_password: str | None = _master_creds["ssh_password"]
        ssh_key: str | None = _master_creds["ssh_key"]

        if not ssh_user:
            _err = (
                f"No SSH user could be resolved for master {master.name!r} — set SSH "
                "credentials on the master record (or the linked node), or configure "
                "the global bootstrap user in Settings → Bootstrap."
            )
            logger.warning("provision_master: %s master_id=%s", _err, salt_master_id)
            master.provision_status = "error"
            master.provision_error = _err
            db.commit()
            return {"status": "error", "reason": _err}

        # Resolve — or generate + persist — the salt-api credentials (#976).
        # Persisted by the db.commit() below when flipping provision_status.
        api_password: str = _ensure_master_api_creds(master)

        # ------------------------------------------------------------------
        # 2. Create MasterProvisionRun + flip provision_status → provisioning
        # ------------------------------------------------------------------
        prun = MasterProvisionRun(
            salt_master_id=master_uuid,
            action=action,
            status="running",
            started_at=datetime.now(UTC),
        )
        db.add(prun)
        master.provision_status = "provisioning"
        master.provision_error = None
        db.commit()
        prun_id: _uuid.UUID = prun.id

    # ------------------------------------------------------------------
    # 3. Pre-flight: detect OS via SSH; bail on unreachable host
    # ------------------------------------------------------------------
    _wrote_terminal = False
    provision_error: str | None = None
    runner = None
    thread = None
    rc_display: int | str = "N/A"

    try:
        with tempfile.TemporaryDirectory(prefix="kri-provision-") as tmpdir:
            # Write SSH key to temp file if using key auth
            key_file_path: str | None = None
            if ssh_key:
                key_path = Path(tmpdir) / "id_provision"
                key_path.write_text(ssh_key)
                key_path.chmod(0o600)
                key_file_path = str(key_path)

            # Build SSH extra args for OS detect (no known_hosts for provision — TOFU)
            _detect_extra: list[str] = ["-o", "StrictHostKeyChecking=accept-new"]
            if key_file_path:
                _detect_extra += ["-i", key_file_path]

            uname_output = _detect_os_family(ssh_host, ssh_user, _detect_extra, ssh_password=ssh_password)
            if uname_output is None:
                # Host unreachable — fail immediately without running playbook
                _err = (
                    f"SSH pre-flight failed: cannot reach {ssh_user}@{ssh_host}. "
                    "Check ssh_host, ssh_user, and SSH credentials on the master record."
                )
                logger.error("provision_master: %s master_id=%s", _err, salt_master_id)
                with get_sync_db() as _db:
                    _m = _db.execute(select(SaltMaster).where(SaltMaster.id == master_uuid)).scalar_one_or_none()
                    _r = _db.execute(
                        select(MasterProvisionRun).where(MasterProvisionRun.id == prun_id)
                    ).scalar_one_or_none()
                    if _m:
                        _m.provision_status = "failed"
                        _m.provision_error = _err
                    if _r:
                        _r.status = "failed"
                        _r.finished_at = datetime.now(UTC)
                        _r.error = _err
                    _db.commit()
                _wrote_terminal = True
                return {"status": "failed", "reason": _err, "salt_master_id": salt_master_id}

            # Map uname output to canonical os_family
            os_family: str = "Darwin" if uname_output == "Darwin" else "Linux"
            playbook_name = _MASTER_PLAYBOOKS[os_family]
            logger.info(
                "provision_master: detected os_family=%s → playbook=%s master_id=%s",
                os_family,
                playbook_name,
                salt_master_id,
            )

            # ------------------------------------------------------------------
            # 4. Build inventory + run Ansible with live streaming
            # ------------------------------------------------------------------
            inv_path = Path(tmpdir) / "inventory.ini"
            if key_file_path:
                inv_path.write_text(
                    f"[targets]\n"
                    f"{ssh_host} ansible_host={ssh_host} "
                    f"ansible_user={ssh_user} "
                    f"ansible_ssh_private_key_file={key_file_path}\n"
                )
            else:
                inv_path.write_text(f"[targets]\n{ssh_host} ansible_host={ssh_host} ansible_user={ssh_user}\n")
            inv_path.chmod(0o600)

            password_extravars: dict[str, str] = {}
            if not key_file_path and ssh_password:
                password_extravars["ansible_ssh_pass"] = ssh_password
                password_extravars["ansible_become_password"] = ssh_password

            ssh_args = "-F /dev/null -o StrictHostKeyChecking=accept-new"
            if key_file_path:
                ssh_args += f" -i {key_file_path}"

            stdout_lines: list[str] = []
            _trunc_ref: dict = {"size": 0, "truncated": False}
            _last_task_ref: dict = {"task": ""}
            _buf_lock = _threading.Lock()
            last_db_write: float = time.time()

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

            _provision_playbook = str(_PLAYBOOKS_DIR / playbook_name)
            _extravars = {
                "target_host": ssh_host,
                "ansible_user": ssh_user,
                "kri_salt_api_password": api_password,
                **password_extravars,
            }
            # Emit the full effective command (secrets masked) at the top of the log (#960).
            _append_capped(stdout_lines, _format_ansible_cmdline(_provision_playbook, str(inv_path), _extravars), _trunc_ref)

            thread, runner = ansible_runner.run_async(
                private_data_dir=tmpdir,
                playbook=_provision_playbook,
                inventory=str(inv_path),
                extravars=_extravars,
                envvars={
                    "ANSIBLE_COLLECTIONS_PATH": str(_PLAYBOOKS_DIR / "collections" / "installed"),
                    "ANSIBLE_SSH_ARGS": ssh_args,
                    "ANSIBLE_FORCE_COLOR": "1",
                    "PYTHONUNBUFFERED": "1",
                },
                event_handler=_event_handler,
                quiet=True,
                rotate_artifacts=0,
                timeout=_PROVISION_TIMEOUT_SECONDS,
            )

            # Non-blocking flush loop: flush incremental logs every _LOG_BATCH_INTERVAL seconds
            while thread.is_alive():
                now = time.time()
                if now - last_db_write >= _LOG_BATCH_INTERVAL:
                    with _buf_lock:
                        snapshot = list(stdout_lines)
                    joined = "\n".join(snapshot)
                    with get_sync_db() as _db:
                        _r = _db.execute(
                            select(MasterProvisionRun).where(MasterProvisionRun.id == prun_id)
                        ).scalar_one_or_none()
                        if _r:
                            _r.ansible_stdout = joined
                        _db.commit()
                    last_db_write = now
                time.sleep(1)
            thread.join()

        # ------------------------------------------------------------------
        # 5. Classify outcome
        # ------------------------------------------------------------------
        full_stdout = "\n".join(stdout_lines)
        last_task = _last_task_ref["task"]
        rc_display = runner.rc if runner is not None and runner.rc is not None else "N/A"
        final_status = runner.status if runner is not None else "error"

        _prov_timeout_min = _PROVISION_TIMEOUT_SECONDS // 60
        if final_status == "timeout":
            provision_error = (
                f"Timed out after {_prov_timeout_min} minutes. Last task: {last_task}"
                if last_task
                else f"Timed out after {_prov_timeout_min} minutes."
            )
        elif final_status != "successful" or runner.rc != 0:
            _cat = _classify_ansible_failure_category(full_stdout)
            if _cat == "salt_master_gate":
                provision_error = (
                    "SSH reached the master node, but it cannot reach a salt-master on "
                    "4505/4506 — check network/firewall"
                )
            elif _cat == "ssh_auth":
                provision_error = "SSH auth failed: check SSH username/password on the master record"
            elif _cat == "ssh_unreachable":
                provision_error = f"SSH unreachable: check ssh_host ({ssh_host}) and SSH credentials"
            else:
                provision_error = f"ansible rc={rc_display} status={final_status}"

            logger.error(
                "provision_master: ansible failure rc=%s status=%s last_task=%r master_id=%s",
                rc_display,
                final_status,
                last_task,
                salt_master_id,
            )

        # ------------------------------------------------------------------
        # 6. Persist terminal state + optionally run probe on success
        # ------------------------------------------------------------------
        _succeeded = final_status == "successful" and runner is not None and runner.rc == 0

        # Run post-provision probe on success to refresh status/checks
        probe_result: "dict | None" = None
        if _succeeded:
            import asyncio

            try:
                # Read master fields inside the DB context, then release the session
                # before calling run_probe() — holding the session during network I/O
                # exhausts the sync pool under load (#738).
                _fresh_master = None
                with get_sync_db() as _pdb:
                    _fresh_master = _pdb.execute(
                        select(SaltMaster).where(SaltMaster.id == master_uuid)
                    ).scalar_one_or_none()
                    if _fresh_master:
                        _pdb.expunge(_fresh_master)
                # DB session is now released; run the network probe outside.
                if _fresh_master:
                    probe_result = dict(asyncio.run(run_probe(_fresh_master)))
            except Exception as _pe:  # noqa: BLE001
                logger.warning(
                    "provision_master: probe after provision failed for master_id=%s: %s",
                    salt_master_id,
                    _pe,
                )

        with get_sync_db() as db:
            _m = db.execute(select(SaltMaster).where(SaltMaster.id == master_uuid)).scalar_one_or_none()
            _r = db.execute(select(MasterProvisionRun).where(MasterProvisionRun.id == prun_id)).scalar_one_or_none()

            if _m:
                if _succeeded:
                    _m.provision_status = "provisioned"
                    _m.provision_error = None
                    _m.os_family = os_family
                    _m.last_provisioned_at = datetime.now(UTC)
                    # Update status from probe if available
                    if probe_result:
                        _m.status = probe_result.get("status", _m.status)
                        _m.checks = probe_result.get("checks")  # type: ignore[assignment]
                        _m.last_checked_at = datetime.now(UTC)
                        failed_checks = [c for c in (probe_result.get("checks") or []) if c.get("status") == "fail"]
                        _m.last_error = failed_checks[0]["detail"] if failed_checks else None
                else:
                    _m.provision_status = "failed"
                    _m.provision_error = provision_error

            if _r:
                _r.finished_at = datetime.now(UTC)
                _r.status = "completed" if _succeeded else "failed"
                _r.ansible_stdout = full_stdout or f"rc={rc_display} status={final_status}"
                _r.error = provision_error

            db.commit()

        _wrote_terminal = True

    except SoftTimeLimitExceeded:
        logger.warning("provision_master: soft time limit exceeded for master_id=%s", salt_master_id)
        with get_sync_db() as db:
            _m = db.execute(select(SaltMaster).where(SaltMaster.id == master_uuid)).scalar_one_or_none()
            if _m and _m.provision_status == "provisioning":
                _m.provision_status = "failed"
                _m.provision_error = "Celery task soft time limit exceeded — provision was terminated."
            db.commit()
        raise

    except Exception as _exc:
        _err_msg = f"Unexpected error during provision: {type(_exc).__name__}: {_exc}"
        logger.exception("provision_master: unhandled exception for master_id=%s", salt_master_id)
        with get_sync_db() as db:
            _m = db.execute(select(SaltMaster).where(SaltMaster.id == master_uuid)).scalar_one_or_none()
            if _m and _m.provision_status == "provisioning":
                _m.provision_status = "failed"
                _m.provision_error = _err_msg
            db.commit()
        raise

    finally:
        if not _wrote_terminal:
            # Any exception path that didn't set terminal status: finalize the run record
            with get_sync_db() as db:
                _r = db.execute(
                    select(MasterProvisionRun)
                    .where(MasterProvisionRun.salt_master_id == master_uuid)
                    .where(MasterProvisionRun.status == "running")
                    .order_by(MasterProvisionRun.started_at.desc())
                ).scalar_one_or_none()
                if _r:
                    _r.status = "failed"
                    _r.finished_at = datetime.now(UTC)
                db.commit()

    return {
        "status": runner.status if runner is not None else "error",
        "rc": rc_display,
        "salt_master_id": salt_master_id,
        "action": action,
        "os_family": os_family if uname_output is not None else "unknown",
    }


# ---------------------------------------------------------------------------
# Master-promotion Phase C — attach minions to a master, additively (#977)
# ---------------------------------------------------------------------------

_RECONFIGURE_TIMEOUT_SECONDS = 300  # 5 minutes — thin re-render + restart, not a full install


def _additive_master_list(cur_addr: str | None, target_addr: str) -> list[str]:
    """Build the additive (HA) ``salt_masters`` list for a minion re-point (#977).

    The re-pointed minion's rendered config must list BOTH the current master's
    address and the target master's address (unique, order preserved) so it
    gains the target as a failover master without losing its existing one.
    When ``cur_addr`` is falsy (no prior master) or equal to ``target_addr``
    (already pointed at the target) the result collapses to a single entry —
    never a duplicate.
    """
    candidates = [addr for addr in (cur_addr, target_addr) if addr]
    return list(dict.fromkeys(candidates))


@celery_app.task(
    name="fleet_platform.workers.ansible_tasks.reconfigure_minions",
    bind=True,
    max_retries=0,
    queue="ansible",  # dedicated long-job queue — isolates from control plane (#579)
    acks_late=False,
)
def reconfigure_minions(self, master_id: str, node_ids: list[str]) -> dict:
    """Re-point selected minions at ``master_id``, additively (HA attach, #977).

    For each node: builds the additive ``salt_masters`` list (current master's
    address + target master's address, deduped preserving order), re-renders
    the minion config + restarts the service via
    ``playbooks/reconfigure_minion_masters.yml``, accepts the minion's key on
    the target master (salt-api ``key.accept`` scoped to that minion_id only —
    the shared master keypair means no new key TRUST is needed on the minion
    itself), then sets ``node.salt_master_id`` to the target master so it owns
    the node in the UI and can command it.

    Never raises on a per-node failure — failures are collected and returned
    so one bad node does not abort the whole batch.
    """
    from fleet_platform.services.salt_api_client import SaltApiError, run_wheel

    target_uuid = _uuid.UUID(master_id)
    reconfigured: list[str] = []
    failed: list[str] = []

    for node_id in node_ids:
        node_uuid = _uuid.UUID(node_id)

        # 1. Load node + target master + node's current master, all in-session,
        # capturing scalars before the session closes (avoid DetachedInstanceError).
        with get_sync_db() as db:
            target_master = db.execute(select(SaltMaster).where(SaltMaster.id == target_uuid)).scalar_one_or_none()
            node = db.execute(select(Node).where(Node.id == node_uuid)).scalar_one_or_none()
            if target_master is None or node is None:
                logger.warning(
                    "reconfigure_minions: master or node not found master_id=%s node_id=%s", master_id, node_id
                )
                failed.append(node_id)
                continue

            cur_master = None
            if node.salt_master_id:
                cur_master = db.execute(
                    select(SaltMaster).where(SaltMaster.id == node.salt_master_id)
                ).scalar_one_or_none()

            target_addr = target_master.address
            cur_addr = cur_master.address if cur_master is not None else None
            additive = _additive_master_list(cur_addr, target_addr)

            minion_id = node.minion_id
            target_ip = node.ip_address or node.bootstrap_ip
            node_ssh_host_key = node.ssh_host_key

            if not target_ip:
                logger.warning("reconfigure_minions: node %s has no ip_address/bootstrap_ip", node_id)
                failed.append(minion_id or node_id)
                continue

            # 2. Resolve the NODE's SSH creds (mirrors bootstrap_node — this is the
            # minion host we SSH into, not the master's own creds).
            resolved_creds = resolve_node_credentials_sync(node, db)
            ssh_user = resolved_creds["ssh_user"] or "admin"
            ssh_password = resolved_creds["ssh_password"]
            node_ssh_key = resolved_creds["ssh_key"] or None

        if not ssh_password and not node_ssh_key:
            logger.warning("reconfigure_minions: no usable SSH credentials for node_id=%s", node_id)
            failed.append(minion_id or node_id)
            continue

        # 3. Run the re-point playbook against this one minion.
        try:
            with tempfile.TemporaryDirectory(prefix="kri-reconfigure-") as tmpdir:
                key_file_path: str | None = None
                if node_ssh_key:
                    key_path = Path(tmpdir) / "id_reconfigure"
                    key_path.write_text(node_ssh_key)
                    key_path.chmod(0o600)
                    key_file_path = str(key_path)

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

                # TOFU: reuse the node's stored host key for strict verification
                # if available, otherwise accept on first connection (mirrors
                # bootstrap_node — this node has already been bootstrapped once).
                known_hosts_file: str | None = None
                if node_ssh_host_key:
                    _kh_token = to_known_hosts_token(node_ssh_host_key)
                    if _kh_token:
                        tmp_kh = tempfile.NamedTemporaryFile(mode="w", suffix=".known_hosts", delete=False)
                        tmp_kh.write(f"{target_ip} {_kh_token}\n")
                        tmp_kh.close()
                        known_hosts_file = tmp_kh.name
                        strict_check = f"-o StrictHostKeyChecking=yes -o UserKnownHostsFile={known_hosts_file}"
                    else:
                        strict_check = "-o StrictHostKeyChecking=accept-new"
                else:
                    strict_check = "-o StrictHostKeyChecking=accept-new"

                ssh_args = f"-F /dev/null {strict_check}"
                if key_file_path:
                    ssh_args += f" -i {key_file_path}"

                password_extravars: dict[str, str] = {}
                if not key_file_path and ssh_password:
                    password_extravars["ansible_ssh_pass"] = ssh_password
                    password_extravars["ansible_become_password"] = ssh_password

                extravars = {
                    "salt_masters": additive,
                    "minion_id": minion_id,
                    **password_extravars,
                }

                playbook = str(_PLAYBOOKS_DIR / "reconfigure_minion_masters.yml")
                run = ansible_runner.run(
                    private_data_dir=tmpdir,
                    playbook=playbook,
                    inventory=str(inv_path),
                    extravars=extravars,
                    envvars={
                        "ANSIBLE_COLLECTIONS_PATH": str(_PLAYBOOKS_DIR / "collections" / "installed"),
                        "ANSIBLE_SSH_ARGS": ssh_args,
                        "PYTHONUNBUFFERED": "1",
                    },
                    quiet=True,
                    rotate_artifacts=0,
                    timeout=_RECONFIGURE_TIMEOUT_SECONDS,
                )

                if known_hosts_file:
                    Path(known_hosts_file).unlink(missing_ok=True)

            if run is None or run.status != "successful" or run.rc != 0:
                logger.error(
                    "reconfigure_minions: ansible failed for node_id=%s minion_id=%s rc=%s status=%s",
                    node_id,
                    minion_id,
                    getattr(run, "rc", "N/A"),
                    getattr(run, "status", "error"),
                )
                failed.append(minion_id or node_id)
                continue

        except Exception:
            logger.exception("reconfigure_minions: unexpected error for node_id=%s", node_id)
            failed.append(minion_id or node_id)
            continue

        # 4. Accept the minion's key on the target master, scoped to this minion
        # only — the shared master keypair means no new TRUST is needed, just
        # acceptance on the newly-owning master. Never fails the whole batch.
        try:
            run_wheel(target_master, "key.accept", match=minion_id)
        except SaltApiError as exc:
            logger.warning(
                "reconfigure_minions: salt-api key.accept failed master=%s minion_id=%s: %s",
                target_master.name,
                minion_id,
                exc.reason,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "reconfigure_minions: key.accept unexpected error minion_id=%s: %s", minion_id, exc
            )

        # 5. Re-point ownership: the target master now owns this node in kri.
        with get_sync_db() as db:
            _n = db.execute(select(Node).where(Node.id == node_uuid)).scalar_one_or_none()
            if _n:
                _n.salt_master_id = target_uuid
                db.commit()

        reconfigured.append(minion_id)

    return {"status": "ok", "reconfigured": reconfigured, "failed": failed}
