"""Unit tests for #1019 — master-first bootstrap.

When a bootstrap request opts in with ``as_master=True``, the node must be
stood up as its OWN salt-master FIRST (so the minion's reachability gate
passes), THEN the minion is bootstrapped — via a Celery chain
(``provision_master`` -> ``bootstrap_node``). This reverses #1006's removal
of the ``as_master`` flag, but with correct ordering (no deadlock): #1006
removed it because same-call ordering deadlocked (minion waiting on a master
that hadn't been provisioned yet); #1019 fixes that with an explicit chain.

``as_master=False`` (the default) must behave exactly as before #1019 —
a bare ``bootstrap_node.delay(...)`` call, no SaltMaster row touched.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fleet_platform.services.bootstrap_svc import BootstrapGroupRequired, queue_node_bootstrap


def _make_node(hostname: str = "node1") -> MagicMock:
    node = MagicMock()
    node.id = uuid.uuid4()
    node.hostname = hostname
    node.minion_id = f"{hostname}.example.com"
    return node


def _make_db() -> AsyncMock:
    db = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.flush = AsyncMock()
    db.add = MagicMock()
    return db


def _result(scalar_one_or_none=None, scalar_one=None):
    r = MagicMock()
    r.scalar_one_or_none.return_value = scalar_one_or_none
    r.scalar_one.return_value = scalar_one
    return r


# ── as_master=False: unchanged bare-delegate path ──────────────────────────


@pytest.mark.asyncio
@patch("fleet_platform.services.bootstrap_svc.audit", new_callable=AsyncMock)
@patch("fleet_platform.services.bootstrap_svc.node_has_group", new_callable=AsyncMock, return_value=True)
@patch("celery.chain")
@patch("fleet_platform.workers.ansible_tasks.provision_master")
@patch("fleet_platform.workers.ansible_tasks.bootstrap_node")
async def test_as_master_false_uses_bare_delegate(
    mock_bootstrap_node, mock_provision_master, mock_chain, mock_has_group, mock_audit
):
    node = _make_node()
    db = _make_db()

    result = await queue_node_bootstrap(
        db,
        node,
        target_ip="10.0.0.5",
        actor="a@b.com",
        as_master=False,
    )

    mock_bootstrap_node.delay.assert_called_once()
    mock_chain.assert_not_called()
    mock_provision_master.si.assert_not_called()
    db.add.assert_not_called()
    assert result is mock_bootstrap_node.delay.return_value


# ── as_master=True, no existing master at the endpoint ─────────────────────


@pytest.mark.asyncio
@patch("fleet_platform.services.platform_settings_svc.encrypt_secret", return_value="enc-secret")
@patch("fleet_platform.services.bootstrap_svc.audit", new_callable=AsyncMock)
@patch("fleet_platform.services.bootstrap_svc.node_has_group", new_callable=AsyncMock, return_value=True)
@patch("celery.chain")
@patch("fleet_platform.workers.ansible_tasks.provision_master")
@patch("fleet_platform.workers.ansible_tasks.bootstrap_node")
async def test_as_master_true_no_existing_master_creates_and_chains(
    mock_bootstrap_node, mock_provision_master, mock_chain, mock_has_group, mock_audit, mock_encrypt
):
    node = _make_node(hostname="mm1")
    db = _make_db()

    # 1) lookup by endpoint -> not found
    # 2) lookup by name -> no clash
    # 3) count() -> 0 (first master)
    db.execute = AsyncMock(
        side_effect=[
            _result(scalar_one_or_none=None),
            _result(scalar_one_or_none=None),
            _result(scalar_one=0),
        ]
    )

    result = await queue_node_bootstrap(
        db,
        node,
        target_ip="10.0.0.5",
        actor="a@b.com",
        as_master=True,
    )

    # A new SaltMaster row was created and added to the session
    db.add.assert_called_once()
    (added_master,) = db.add.call_args.args
    assert added_master.name == "mm1"
    assert added_master.address == "10.0.0.5"
    assert added_master.publish_port == 4505
    assert added_master.ret_port == 4506
    assert added_master.salt_api_port == 4507
    assert added_master.provision_status == "provisioning"
    assert added_master.node_id == node.id
    assert added_master.is_default is True  # first master in the fleet

    # bare bootstrap_node.delay must NOT be used — chain path instead
    mock_bootstrap_node.delay.assert_not_called()
    mock_provision_master.si.assert_called_once()
    mock_bootstrap_node.si.assert_called_once()
    mock_chain.assert_called_once_with(
        mock_provision_master.si.return_value,
        mock_bootstrap_node.si.return_value,
    )
    mock_chain.return_value.apply_async.assert_called_once_with(queue="ansible")
    assert result is mock_chain.return_value.apply_async.return_value

    # bootstrap_node.si was chained with the new master's id
    _, si_kwargs = mock_bootstrap_node.si.call_args
    assert si_kwargs["salt_master_ids"] == [str(added_master.id)]


# ── as_master=True + selected masters → own + selected (optional HA, #1022) ──


@pytest.mark.asyncio
@patch("fleet_platform.services.platform_settings_svc.encrypt_secret", return_value="enc-secret")
@patch("fleet_platform.services.bootstrap_svc.audit", new_callable=AsyncMock)
@patch("fleet_platform.services.bootstrap_svc.node_has_group", new_callable=AsyncMock, return_value=True)
@patch("celery.chain")
@patch("fleet_platform.workers.ansible_tasks.provision_master")
@patch("fleet_platform.workers.ansible_tasks.bootstrap_node")
async def test_as_master_combines_own_and_selected_masters_for_ha(
    mock_bootstrap_node, mock_provision_master, mock_chain, mock_has_group, mock_audit, mock_encrypt
):
    """#1022: a self-master node enrols into its OWN master PLUS any additional
    masters the caller selected (deduped, own-first)."""
    node = _make_node(hostname="mm1")
    db = _make_db()
    db.execute = AsyncMock(
        side_effect=[
            _result(scalar_one_or_none=None),  # endpoint lookup: none
            _result(scalar_one_or_none=None),  # name lookup: no clash
            _result(scalar_one=0),  # count: first master
        ]
    )

    await queue_node_bootstrap(
        db,
        node,
        target_ip="10.0.0.5",
        actor="a@b.com",
        as_master=True,
        salt_master_ids=["ha-other-master"],
    )

    (added_master,) = db.add.call_args.args
    _, si_kwargs = mock_bootstrap_node.si.call_args
    assert si_kwargs["salt_master_ids"] == [str(added_master.id), "ha-other-master"]


# ── as_master=True, existing master already at the endpoint (reuse) ────────


@pytest.mark.asyncio
@patch("fleet_platform.services.bootstrap_svc.audit", new_callable=AsyncMock)
@patch("fleet_platform.services.bootstrap_svc.node_has_group", new_callable=AsyncMock, return_value=True)
@patch("celery.chain")
@patch("fleet_platform.workers.ansible_tasks.provision_master")
@patch("fleet_platform.workers.ansible_tasks.bootstrap_node")
async def test_as_master_true_reuses_existing_master(
    mock_bootstrap_node, mock_provision_master, mock_chain, mock_has_group, mock_audit
):
    node = _make_node(hostname="mm2")
    db = _make_db()

    existing_master = MagicMock()
    existing_master.id = uuid.uuid4()
    db.execute = AsyncMock(return_value=_result(scalar_one_or_none=existing_master))

    result = await queue_node_bootstrap(
        db,
        node,
        target_ip="10.0.0.9",
        actor="a@b.com",
        as_master=True,
    )

    # No new SaltMaster created — the existing row is reused
    db.add.assert_not_called()

    mock_bootstrap_node.delay.assert_not_called()
    mock_provision_master.si.assert_called_once_with(str(existing_master.id), "install")
    _, si_kwargs = mock_bootstrap_node.si.call_args
    assert si_kwargs["salt_master_ids"] == [str(existing_master.id)]
    mock_chain.assert_called_once()
    assert result is mock_chain.return_value.apply_async.return_value


@pytest.mark.asyncio
@patch("fleet_platform.services.bootstrap_svc.audit", new_callable=AsyncMock)
@patch("fleet_platform.services.bootstrap_svc.node_has_group", new_callable=AsyncMock, return_value=True)
async def test_as_master_true_name_clash_raises(mock_has_group, mock_audit):
    """A name clash on a *different* endpoint fails loud instead of auto-suffixing."""
    node = _make_node(hostname="mm3")
    db = _make_db()

    name_clash = MagicMock()
    name_clash.id = uuid.uuid4()
    db.execute = AsyncMock(
        side_effect=[
            _result(scalar_one_or_none=None),  # no master at this endpoint
            _result(scalar_one_or_none=name_clash),  # but the name is taken
        ]
    )

    with pytest.raises(BootstrapGroupRequired, match="mm3"):
        await queue_node_bootstrap(
            db,
            node,
            target_ip="10.0.0.5",
            actor="a@b.com",
            as_master=True,
        )

    db.add.assert_not_called()


# ── schema contract ─────────────────────────────────────────────────────────


def test_bootstrap_request_has_as_master_field():
    from fleet_platform.schemas.ansible import BootstrapRequest

    req = BootstrapRequest(minion_id="mm1", target_ip="10.0.0.1")
    assert req.as_master is False

    req2 = BootstrapRequest(minion_id="mm1", target_ip="10.0.0.1", as_master=True)
    assert req2.as_master is True


def test_import_commit_request_has_as_master_field():
    from fleet_platform.schemas.node_import import ImportCommitRequest

    req = ImportCommitRequest(rows=[])
    assert req.as_master is False

    req2 = ImportCommitRequest(rows=[], as_master=True)
    assert req2.as_master is True
