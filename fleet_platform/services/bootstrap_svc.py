"""Shared node-bootstrap queuing logic.

Both the dedicated bootstrap endpoint (``POST /api/v1/ansible/bootstrap``) and the
bulk-import commit path (``POST /api/v1/fleet/nodes/import/commit`` with
``auto_bootstrap``) funnel through :func:`queue_node_bootstrap` so they share one
implementation of: group enforcement, audit, and the Celery dispatch. This keeps
the two entry points at parity (#consolidate-add-node). SSH credentials are
resolved from the node's group (credential_groups) at bootstrap-worker time
(#986 Phase 2c) rather than persisted per-node here.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.core.audit import audit
from fleet_platform.models.node import Node
from fleet_platform.models.salt_master import SaltMaster
from fleet_platform.services.credential_resolver import node_has_group


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
    # Runtime overrides for #830
    node_exporter_version: str | None = None,
    node_exporter_listen_address: str | None = None,
    node_exporter_url_override: str | None = None,
    # Master-first bootstrap (#1019)
    as_master: bool = False,
):
    """Mark the node pending, audit, commit, and queue bootstrap.

    Returns the Celery task handle. Raises :class:`BootstrapGroupRequired` when
    ``require_group`` and the node is not yet in any group.

    ``ssh_password``/``ssh_key`` are accepted for backward compatibility with
    existing callers but are no longer persisted as a per-node ``Credential``
    (#986 Phase 2c) — the worker resolves credentials from the node's group via
    :func:`fleet_platform.services.credential_resolver.resolve_node_credentials`.
    Secrets are never forwarded to the Celery task (that would put plaintext on
    the Redis broker — see #495).

    ``as_master`` (#1019, reverses #1006's removal with correct ordering):
    when set, the node is stood up as its OWN salt-master FIRST (so the
    minion's reachability gate passes), then the minion is bootstrapped — via
    a Celery chain (``provision_master`` → ``bootstrap_node``). This avoids the
    deadlock that #1006 removed (minion waiting on a master that never
    provisions because bootstrap hadn't happened yet).
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

    # Bootstrap-time ssh_username/password/key are no longer persisted as a
    # per-node Credential (#986 Phase 2c). Credentials resolve from the node's
    # group via credential_resolver.resolve_node_credentials, already wired
    # through the bootstrap worker (#965). The parameters remain accepted here
    # so existing callers (dedicated bootstrap endpoint, bulk-import auto_bootstrap)
    # don't break — they are simply unused for credential persistence now.

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

    if not as_master:
        return bootstrap_node.delay(
            str(node.id),
            target_ip,
            ssh_username=ssh_username,
            salt_master_ids=salt_master_ids,
            node_exporter_version=node_exporter_version,
            node_exporter_listen_address=node_exporter_listen_address,
            node_exporter_url_override=node_exporter_url_override,
        )

    # --- Master-first bootstrap (#1019) ---------------------------------
    # Reuse-or-create the SaltMaster row for this node's own endpoint, then
    # chain provision_master → bootstrap_node so the master is installed
    # before the minion's reachability gate is evaluated.
    existing = (
        await db.execute(
            select(SaltMaster).where(
                SaltMaster.address == target_ip,
                SaltMaster.publish_port == 4505,
                SaltMaster.ret_port == 4506,
                SaltMaster.salt_api_port == 4507,
            )
        )
    ).scalar_one_or_none()

    if existing is not None:
        master_id = existing.id
    else:
        name = node.hostname or target_ip
        name_clash = (await db.execute(select(SaltMaster).where(SaltMaster.name == name))).scalar_one_or_none()
        if name_clash is not None:
            raise BootstrapGroupRequired(
                f"A salt-master named '{name}' already exists — rename it or provision manually"
            )

        import secrets as _secrets

        from fleet_platform.services.platform_settings_svc import encrypt_secret

        is_first = (await db.execute(select(func.count()).select_from(SaltMaster))).scalar_one() == 0
        new_master = SaltMaster(
            name=name,
            address=target_ip,
            enabled=True,
            is_default=is_first,
            publish_port=4505,
            ret_port=4506,
            salt_api_port=4507,
            use_tls=True,
            api_url=f"https://{target_ip}:4507",
            api_user="kri-api",
            api_password_enc=encrypt_secret(_secrets.token_urlsafe(24)),
            api_eauth="pam",
            provision_status="provisioning",
            node_id=node.id,
        )
        db.add(new_master)
        await db.flush()
        master_id = new_master.id

    await db.commit()

    from celery import chain

    from fleet_platform.workers.ansible_tasks import provision_master

    # Enrol into the node's OWN master plus any additional masters the caller
    # selected (optional multi-master HA, #1022) — deduped, own-first.
    _own = str(master_id)
    _ha_master_ids = [_own] + [m for m in (salt_master_ids or []) if str(m) != _own]

    sig = chain(
        provision_master.si(_own, "install"),
        bootstrap_node.si(
            str(node.id),
            target_ip,
            salt_master_ids=_ha_master_ids,
            node_exporter_version=node_exporter_version,
            node_exporter_listen_address=node_exporter_listen_address,
            node_exporter_url_override=node_exporter_url_override,
        ),
    )
    return sig.apply_async(queue="ansible")
