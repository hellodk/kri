"""Resolve effective SSH credentials for a node.

Priority chain (first match wins):
  1. Credential group    (member group's credential via the ``credential_groups``
                          association; highest ``credential_priority`` then name)
  2. Controller key      (node was bootstrapped — ssh_host_key set — and
                          ~/.kri/id_rsa exists)

Design intent: tier 1 is the ONLY per-node secret source (#989 — GROUP-ONLY
contract). There is no per-node credential, no legacy ``Group.credential_id``
column, and no global-password fallback: a node's secret always comes from a
group it belongs to. Tier 2 applies only to nodes that have been bootstrapped
(TOFU host-key recorded) and have no group credential; the controller private
key was installed on the node during bootstrap. If neither tier resolves a
usable secret, :func:`resolve_node_credentials` / :func:`resolve_node_credentials_sync`
return a credential-less dict (``credential_source: 'none'``) rather than
raising — callers that *require* a secret must use
:func:`require_usable_node_credentials` / :func:`require_usable_node_credentials_sync`.

Single secret-resolution path (#748 — ARC-4, contracted further by #989): node/
group SSH creds live solely in the first-class ``Credential`` store, referenced
via the ``credential_groups`` association. The deprecated inline
``ssh_username`` / ``ssh_password_enc`` / ``ssh_key_enc`` / ``ssh_auth_mode``
columns, the per-node ``Node.credential_id`` FK, the legacy
``Group.credential_id`` FK, and the global password fallback (platform setting
``SSH_PASSWORD``) are ALL gone. ``SSH_USERNAME`` is still read — but only as
the SSH *login user* for the controller-key and credential-less tiers, never as
a password credential.

Callers that *require* a usable secret (WebSSH, VNC, password-mode bootstrap)
should use :func:`require_usable_node_credentials` /
:func:`require_usable_node_credentials_sync`, which raise
:class:`NoUsableCredentialError` instead of silently returning a credential-less
result.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.models.credential import Credential
from fleet_platform.models.credential_group import CredentialGroup
from fleet_platform.models.group import Group, GroupMember
from fleet_platform.models.node import Node
from fleet_platform.models.platform_setting import PlatformSetting
from fleet_platform.services.platform_settings_svc import (
    SSH_USERNAME,
    _fernet,
    decrypt_secret,
)
from fleet_platform.services.ssh_keypair import _DEFAULT_PRIV

logger = logging.getLogger(__name__)


class NoUsableCredentialError(RuntimeError):
    """Raised when an SSH credential is required but none can be resolved.

    A node with no usable credential-group secret (#989: the ONLY per-node
    secret source) and no controller key has no usable secret. Callers that
    *require* a credential must fail loudly via
    :func:`require_usable_node_credentials` rather than attempt a connection
    with no secret.
    """


def has_usable_secret(creds: dict) -> bool:
    """True if resolved ``creds`` carry a usable secret for their ``auth_mode`` (#701).

    Used by credential-required actions (WebSSH, VNC, password-mode bootstrap) to
    fail loudly instead of silently attempting a connection with no secret.
    """
    if creds.get("auth_mode") == "key":
        return bool(creds.get("ssh_key"))
    return bool(creds.get("ssh_password"))


def _read_controller_key() -> str:
    """Return the controller private key (~/.kri/id_rsa) or '' if absent/unreadable."""
    try:
        return _DEFAULT_PRIV.read_text()
    except OSError:
        return ""


def _decrypt_or_blank(label: str, ident, field: str, ciphertext: str | None) -> str:
    if not ciphertext:
        return ""
    try:
        return decrypt_secret(ciphertext)
    except Exception as exc:
        logger.warning("Fernet decryption failed for %s %s field %s: %s", label, ident, field, exc)
        return ""


def _credential_to_creds(cred: Credential, source: str) -> dict:
    """Map a :class:`Credential` row onto the resolved-creds dict shape.

    ``kind='ssh_key'`` -> key auth (secret is the private key); any other kind
    (``username_password`` / ``token``) -> password auth (secret is the
    password). ``last_used_at`` is touched best-effort for rotation/audit
    visibility (#698) — it persists only if the caller commits the session.
    """
    secret = _decrypt_or_blank("credential", cred.id, "secret", cred.secret_enc)
    try:
        cred.last_used_at = datetime.now(UTC)
    except Exception:  # pragma: no cover — best-effort, never block resolution
        pass
    if cred.kind == "ssh_key":
        return {
            "ssh_user": cred.username or "",
            "ssh_password": "",
            "ssh_key": secret,
            "auth_mode": "key",
            "credential_source": source,
        }
    return {
        "ssh_user": cred.username or "",
        "ssh_password": secret,
        "ssh_key": "",
        "auth_mode": "password",
        "credential_source": source,
    }


def _credential_group_stmt(node_id):
    """Member group whose credential comes via ``credential_groups`` (#984).

    This is the ONLY group/node credential source (#989 — group-only contract).
    Tiebreak when a node belongs to 2+ credential-bearing groups: highest
    ``credential_priority`` then name. Returns ``(Credential, group_name)`` rows.
    """
    return (
        select(Credential, Group.name)
        .select_from(GroupMember)
        .join(Group, Group.id == GroupMember.group_id)
        .join(CredentialGroup, CredentialGroup.group_id == Group.id)
        .join(Credential, Credential.id == CredentialGroup.credential_id)
        .where(GroupMember.node_id == node_id)
        .order_by(Group.credential_priority.desc(), Group.name.asc())
        .limit(1)
    )


def _credential_less_creds(ssh_user: str) -> dict:
    """The terminal result when no tier resolves a usable secret (#989).

    Callers that require a secret fail loudly via ``has_usable_secret`` /
    ``require_usable_node_credentials`` rather than silently falling back to a
    global password — there is no global password tier anymore.
    """
    return {
        "ssh_user": ssh_user,
        "ssh_password": "",
        "ssh_key": "",
        "auth_mode": "password",
        "credential_source": "none",
    }


async def resolve_node_credentials(node: Node, db: AsyncSession) -> dict:
    """Return resolved SSH credentials for a node.

    Returns dict with keys: ssh_user, ssh_password, ssh_key, auth_mode,
    credential_source ('group:<name>' | 'controller' | 'none')
    """
    # 1. Group credential via credential_groups association (#984/#989) — the
    #    ONLY per-node secret source.
    _cg_row = (await db.execute(_credential_group_stmt(node.id))).first()
    if _cg_row is not None:
        _cred, _gname = _cg_row
        creds = _credential_to_creds(_cred, f"group:{_gname}")
        if has_usable_secret(creds):
            return creds

    # 2. Controller key — node was bootstrapped (ssh_host_key set) and key file exists
    if node.ssh_host_key:
        controller_key = _read_controller_key()
        if controller_key:
            ssh_user = await _get_global_setting(db, SSH_USERNAME) or "admin"
            return {
                "ssh_user": ssh_user,
                "ssh_password": "",
                "ssh_key": controller_key,
                "auth_mode": "key",
                "credential_source": "controller",
            }

    # 3. Nothing usable — credential-less result (#989: no global password tier).
    ssh_user = await _get_global_setting(db, SSH_USERNAME) or "admin"
    return _credential_less_creds(ssh_user)


def resolve_node_credentials_sync(node: Node, db) -> dict:
    """Synchronous twin of :func:`resolve_node_credentials` for the Celery worker.

    The playbook worker runs on a sync SQLAlchemy ``Session`` (``get_sync_db``),
    so it cannot await the async resolver. This mirrors the same
    credential-group -> controller -> none priority chain and returns the
    identical dict shape, including ``credential_source`` (#279, #349, #698,
    #989).
    """
    # 1. Group credential via credential_groups association (#984/#989) — the
    #    ONLY per-node secret source.
    _cg_row = db.execute(_credential_group_stmt(node.id)).first()
    if _cg_row is not None:
        _cred, _gname = _cg_row
        creds = _credential_to_creds(_cred, f"group:{_gname}")
        if has_usable_secret(creds):
            return creds

    # 2. Controller key — node was bootstrapped (ssh_host_key set) and key file exists
    if node.ssh_host_key:
        controller_key = _read_controller_key()
        if controller_key:
            return {
                "ssh_user": _get_global_setting_sync(db, SSH_USERNAME) or "admin",
                "ssh_password": "",
                "ssh_key": controller_key,
                "auth_mode": "key",
                "credential_source": "controller",
            }

    # 3. Nothing usable — credential-less result (#989: no global password tier).
    return _credential_less_creds(_get_global_setting_sync(db, SSH_USERNAME) or "admin")


def _no_usable_secret_message(node: Node) -> str:
    minion = getattr(node, "minion_id", None) or getattr(node, "id", "<unknown>")
    return (
        f"No usable SSH credential for node {minion}: link a Credential to one of "
        "its groups, or bootstrap the node so the controller key applies. There is "
        "no per-node or global-password credential source (#989)."
    )


async def require_usable_node_credentials(node: Node, db: AsyncSession) -> dict:
    """Resolve credentials and raise if none carry a usable secret (#748, #989).

    Use from credential-required actions (WebSSH, VNC, password-mode bootstrap)
    that must fail loudly. A node with no resolvable secret raises
    :class:`NoUsableCredentialError` instead of silently degrading.
    """
    creds = await resolve_node_credentials(node, db)
    if not has_usable_secret(creds):
        raise NoUsableCredentialError(_no_usable_secret_message(node))
    return creds


def require_usable_node_credentials_sync(node: Node, db) -> dict:
    """Synchronous twin of :func:`require_usable_node_credentials` (#748)."""
    creds = resolve_node_credentials_sync(node, db)
    if not has_usable_secret(creds):
        raise NoUsableCredentialError(_no_usable_secret_message(node))
    return creds


def _get_global_setting_sync(db, key: str, encrypted: bool = False) -> str:
    row = db.execute(select(PlatformSetting).where(PlatformSetting.key == key)).scalar_one_or_none()
    if not row or not row.value:
        return ""
    if encrypted and row.is_encrypted:
        try:
            return _fernet().decrypt(row.value.encode()).decode()
        except Exception as exc:
            logger.warning("Fernet decryption failed for global platform setting %s: %s", key, exc)
            return ""
    return row.value or ""


async def _get_global_setting(db: AsyncSession, key: str, encrypted: bool = False) -> str:
    result = await db.execute(select(PlatformSetting).where(PlatformSetting.key == key))
    row = result.scalar_one_or_none()
    if not row or not row.value:
        return ""
    if encrypted and row.is_encrypted:
        try:
            return _fernet().decrypt(row.value.encode()).decode()
        except Exception as exc:
            logger.warning(
                "Fernet decryption failed for global platform setting %s: %s",
                key,
                exc,
            )
            return ""
    return row.value or ""


async def node_has_group(node_id, db: AsyncSession) -> bool:
    """Return True if the node belongs to at least one group."""
    result = await db.execute(select(GroupMember).where(GroupMember.node_id == node_id).limit(1))
    return result.scalar_one_or_none() is not None


async def nodes_using_credential(credential_id, db: AsyncSession) -> list[tuple[Node, str]]:
    """Return ``(node, source)`` for every node whose *resolved* credential is ``credential_id`` (#700, #989).

    Resolution-aware: a node counts only if its credential-groups tier
    (highest ``credential_priority``, then name) resolves to a USABLE secret
    pointing at ``credential_id``. Group-only model (#989) — there is no
    node-level or legacy ``Group.credential_id`` tier anymore. This is the
    read-only audit/rotation view; it deliberately ignores the controller/none
    tiers (not Credential rows).
    """
    results: list[tuple[Node, str]] = []

    candidates = (
        (
            await db.execute(
                select(Node)
                .join(GroupMember, GroupMember.node_id == Node.id)
                .join(Group, Group.id == GroupMember.group_id)
                .join(CredentialGroup, CredentialGroup.group_id == Group.id)
                .where(CredentialGroup.credential_id == credential_id)
                .distinct()
            )
        )
        .scalars()
        .all()
    )
    for n in candidates:
        _cg_row = (await db.execute(_credential_group_stmt(n.id))).first()
        if _cg_row is None:
            continue
        _cred, _gname = _cg_row
        if _cred.id != credential_id:
            # A higher-priority group won the tiebreak with a different credential.
            continue
        if has_usable_secret(_credential_to_creds(_cred, f"group:{_gname}")):
            results.append((n, f"group:{_gname}"))

    return results
