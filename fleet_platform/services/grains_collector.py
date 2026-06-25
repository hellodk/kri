# fleet_platform/services/grains_collector.py
"""Low-level grain-collection helpers extracted from ansible_tasks (#750).

Two strategies for fetching a minion's ``grains.items``:
- ``_grains_via_salt_api``: preferred — asks the master over salt-api (#708).
- ``_grains_via_ssh``: legacy fallback — SSH in with the controller key and run
  ``salt-call --local`` when the minion can't be reached through its master.
"""

import logging
import subprocess
import tempfile
from pathlib import Path

from fleet_platform.services.ssh_host_key_svc import to_known_hosts_token

logger = logging.getLogger(__name__)


def _grains_via_salt_api(creds: dict, minion_id: str, timeout: int = 30) -> tuple[dict | None, str | None]:
    """Fetch grains.items for one minion via the salt-api local client (#708).

    The master already manages the minion, so no SSH and no controller key are
    needed. Returns (grains, None) on success, or (None, reason) when the call
    fails or the minion is not currently connected to its master.
    """
    import requests

    api_url = creds.get("api_url") or ""
    if not api_url or not creds.get("api_user"):
        return None, "master api_url/api_user not configured"
    try:
        resp = requests.post(
            f"{api_url}/run",
            json={
                "client": "local",
                "tgt": minion_id,
                "tgt_type": "glob",
                "fun": "grains.items",
                "username": creds["api_user"],
                "password": creds.get("api_password", ""),
                "eauth": creds.get("api_eauth", "pam"),
            },
            timeout=timeout,
            verify=creds.get("tls_verify", False),
        )
        resp.raise_for_status()
        ret = resp.json().get("return", [{}])
        inner = ret[0] if isinstance(ret, list) and ret else {}
        if not isinstance(inner, dict):
            return None, "unexpected salt-api response shape"
        grains = inner.get(minion_id)
        if isinstance(grains, dict) and grains:
            return grains, None
        # Empty return = minion offline / key not accepted / not on this master.
        return None, "minion not connected to master (empty grains.items)"
    except Exception as exc:  # noqa: BLE001
        logger.warning("collect_node_grains: salt-api grains.items failed for %s: %s", minion_id, exc)
        return None, str(exc)[:200]


def _grains_via_ssh(target_ip, ssh_user, minion_id, ssh_host_key) -> tuple[dict | None, str | None]:
    """Legacy fallback: SSH in via the controller key and run salt-call --local.

    Only used when the minion can't be reached through its master (e.g. key not
    yet accepted). Requires ~/.kri/id_rsa to be readable by the worker process.
    """
    import json as _json
    import os as _os2

    controller_priv = Path.home() / ".kri" / "id_rsa"
    with tempfile.TemporaryDirectory(prefix="kri-grains-") as tmpdir:
        if not controller_priv.exists():
            return None, "no controller key present (~/.kri/id_rsa)"
        tmp_key = Path(tmpdir) / "id_ctrl"
        try:
            tmp_key.write_bytes(controller_priv.read_bytes())
        except OSError as exc:
            return None, f"controller key unreadable by worker: {exc}"
        tmp_key.chmod(0o600)
        key_file_path = str(tmp_key)

        # TOFU: use node's stored host key for strict verification if available.
        grains_known_hosts_file: str | None = None
        if ssh_host_key:
            _grains_kh_token = to_known_hosts_token(ssh_host_key)
            if _grains_kh_token:
                tmp_kh2 = tempfile.NamedTemporaryFile(mode="w", suffix=".known_hosts", delete=False)
                tmp_kh2.write(f"{target_ip} {_grains_kh_token}\n")
                tmp_kh2.close()
                grains_known_hosts_file = tmp_kh2.name
                grains_strict_opts = [
                    "-o",
                    "StrictHostKeyChecking=yes",
                    "-o",
                    f"UserKnownHostsFile={grains_known_hosts_file}",
                ]
            else:
                # Stored key unparseable; fall back to accept-new (#840).
                grains_strict_opts = ["-o", "StrictHostKeyChecking=accept-new"]
        else:
            grains_strict_opts = ["-o", "StrictHostKeyChecking=accept-new"]

        ssh_cmd = [
            "ssh",
            "-F",
            "/dev/null",  # skip mounted ~/.ssh/config (UID mismatch in container)
            *grains_strict_opts,
            "-o",
            "ConnectTimeout=15",
            "-o",
            "BatchMode=yes",
            "-i",
            key_file_path,
            f"{ssh_user}@{target_ip}",
            (
                "sudo /opt/homebrew/bin/salt-call --local grains.items --out=json --log-level=warning 2>/dev/null"
                " || sudo /usr/local/bin/salt-call --local grains.items --out=json --log-level=warning 2>/dev/null"
            ),
        ]
        try:
            proc = subprocess.run(ssh_cmd, capture_output=True, text=True, timeout=30)
            if proc.returncode != 0:
                return None, f"ssh failed: {proc.stderr[:200]}"
            parsed = _json.loads(proc.stdout.strip())
            grains = parsed.get("local", parsed)
            if isinstance(grains, dict) and grains:
                return grains, None
            return None, "empty grains from salt-call"
        except subprocess.TimeoutExpired:
            return None, "ssh timeout"
        except Exception as e:  # noqa: BLE001
            return None, str(e)[:200]
        finally:
            if grains_known_hosts_file:
                try:
                    _os2.unlink(grains_known_hosts_file)
                except OSError:
                    pass
