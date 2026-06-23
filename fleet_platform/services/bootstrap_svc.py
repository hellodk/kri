"""Shared node-bootstrap queuing logic.

Both the dedicated bootstrap endpoint (``POST /api/v1/ansible/bootstrap``) and the
bulk-import commit path (``POST /api/v1/fleet/nodes/import/commit`` with
``auto_bootstrap``) funnel through :func:`queue_node_bootstrap` so they share one
implementation of: group enforcement, SSH-credential persistence, audit, and the
Celery dispatch. This keeps the two entry points at parity (#consolidate-add-node).
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.core.audit import audit
from fleet_platform.models.node import Node
from fleet_platform.services.credential_resolver import node_has_group
from fleet_platform.services.ssh_credential_link import upsert_owner_ssh_credential


class BootstrapGroupRequired(Exception):
    """A node must belong to a group before it can be bootstrapped."""


async def queue_node_bootstrap(
    db: AsyncSession,
    node: Node,
    *,
    target_ip: str,
    actor: str,
    ssh_username: str | None = None,
    ssh_password: str | None = None,
    ssh_key: str | None = None,
    salt_master_ids: list[str] | None = None,
    require_group: bool = True,
):
    """Persist SSH creds, mark the node pending, audit, commit, and queue bootstrap.

    Returns the Celery task handle. Raises :class:`BootstrapGroupRequired` when
    ``require_group`` and the node is not yet in any group.

    Secrets are bound to locals and never forwarded to the Celery task (that would
    put plaintext on the Redis broker — see #495); the worker re-reads them from
    the node's persisted ``Credential`` row.
    """
    node.bootstrap_status = "pending"
    node.bootstrap_ip = target_ip
    node.bootstrap_logs = ""  # clear previous run's logs
    node.bootstrap_error = None  # clear previous error

    if require_group and not await node_has_group(node.id, db):
        raise BootstrapGroupRequired(
            "Node must belong to at least one group before bootstrapping. "
            "Add the node to a group first, then configure group SSH credentials."
        )

    auth_mode = "key" if (ssh_key and not ssh_password) else "password"
    cred_id = await upsert_owner_ssh_credential(
        db,
        owner_name=f"node:{node.minion_id}",
        current_credential_id=node.credential_id,
        ssh_username=ssh_username,
        ssh_password=ssh_password,
        ssh_key=ssh_key,
        ssh_auth_mode=auth_mode if (ssh_password or ssh_key) else None,
    )
    if cred_id is not None:
        node.credential_id = cred_id

    await audit(
        db,
        actor=actor,
        action="node.bootstrap.request",
        resource_type="node",
        resource_id=node.id,
        new_value={"minion_id": node.minion_id, "target_ip": target_ip},
    )
    await db.commit()
    await db.refresh(node)

    # Lazy import: avoid a services→workers import cycle at module load.
    from fleet_platform.workers.ansible_tasks import bootstrap_node

    return bootstrap_node.delay(
        str(node.id),
        target_ip,
        ssh_username=ssh_username,
        salt_master_ids=salt_master_ids,
    )
