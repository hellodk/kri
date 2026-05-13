"""
Fleet Platform Salt returner.

Sends Salt job results to the Fleet Platform ingest API.

Installation:
  1. Copy to /srv/salt/_returners/fleet_platform_return.py
  2. Run: salt '*' saltutil.sync_returners
  3. Configure in /etc/salt/minion.d/fleet_platform.conf:

       return: fleet_platform_return

  4. Set in each minion's pillar:
       fleet_platform:
         ingest_url: https://fleet.internal/api/v1/ingest
         node_token: <token from POST /api/v1/nodes/register>
"""

import json
import logging
import urllib.error
import urllib.request

log = logging.getLogger(__name__)


def _cfg(key, default=None):
    return __salt__["config.get"](f"fleet_platform.{key}", default)  # noqa: F821


def returner(ret):
    """POST job result to /api/v1/ingest/executions. Called after every Salt job."""
    ingest_url = _cfg("ingest_url")
    node_token = _cfg("node_token")

    if not ingest_url or not node_token:
        log.warning("fleet_platform_return: ingest_url or node_token not set — skipping")
        return

    payload = {
        "minion_id": ret.get("id", ""),
        "jid": ret.get("jid", ""),
        "return_data": ret.get("return") or {},
        "fun": ret.get("fun", ""),
        "retcode": ret.get("retcode", 0),
        "success": ret.get("success", True),
    }

    try:
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{ingest_url}/executions",
            data=body,
            headers={
                "Content-Type": "application/json",
                "X-Node-Token": node_token,
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            log.debug("fleet_platform_return: posted jid=%s status=%s", payload["jid"], resp.status)
    except urllib.error.URLError as exc:
        log.error("fleet_platform_return: failed to post jid=%s error=%s", payload["jid"], exc)


def prep_jid(nocache=False, passed_jid=None):
    """Return a job ID — delegate to Salt's jid generator."""
    if passed_jid is not None:
        return passed_jid
    return __salt__["jid.gen_jid"]({})  # noqa: F821


def save_load(jid, load, minions=None):
    """Required by Salt returner interface — not used."""


def get_load(jid):
    """Required by Salt returner interface — not used."""
    return {}
