"""Tests for salt minion presence sync (#254, #655).

Covers the DB-driven refactor: task reads connection details from the default
enabled SaltMaster row instead of env vars.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# _runner_call helpers
# ---------------------------------------------------------------------------


def test_runner_call_returns_none_on_connection_error():
    """_runner_call returns None (not raises) on any error."""
    from fleet_platform.workers.salt_presence_tasks import _runner_call

    with patch("requests.post", side_effect=ConnectionError("refused")):
        result = _runner_call("http://salt:8000", "admin", "pw", "pam", False, "manage.up")
    assert result is None


def test_runner_call_parses_list_response():
    """_runner_call extracts minion list from salt-api list response."""
    from fleet_platform.workers.salt_presence_tasks import _runner_call

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"return": [["mm1", "mm2", "mm3"]]}
    mock_resp.raise_for_status = MagicMock()
    with patch("requests.post", return_value=mock_resp):
        result = _runner_call("http://salt:8000", "admin", "pw", "pam", False, "manage.up")
    assert result == ["mm1", "mm2", "mm3"]


def test_runner_call_parses_dict_response():
    """_runner_call handles dict-keyed response from some salt-api versions."""
    from fleet_platform.workers.salt_presence_tasks import _runner_call

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"return": [{"mm1": True, "mm2": True}]}
    mock_resp.raise_for_status = MagicMock()
    with patch("requests.post", return_value=mock_resp):
        result = _runner_call("http://salt:8000", "admin", "pw", "pam", False, "manage.up")
    assert set(result) == {"mm1", "mm2"}


# ---------------------------------------------------------------------------
# sync_minion_presence — skipped cases
# ---------------------------------------------------------------------------


def _make_master(**kwargs) -> SimpleNamespace:
    defaults = dict(
        name="mm",
        api_url="https://salt.local:8080",
        api_user="saltadmin",
        api_eauth="pam",
        tls_verify=False,
        api_password_enc=None,
        enabled=True,
        is_default=True,
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _make_db_with_masters(masters):
    """Return a context-manager mock whose execute() yields the given master list."""
    scalar = MagicMock()
    scalar.scalars.return_value.all.return_value = list(masters)
    execute_mock = MagicMock(return_value=scalar)
    db = MagicMock()
    db.execute = execute_mock
    db.__enter__ = MagicMock(return_value=db)
    db.__exit__ = MagicMock(return_value=False)
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=db)
    ctx.__exit__ = MagicMock(return_value=False)
    return ctx


def test_sync_presence_skips_when_no_master():
    """Returns 'skipped' when no enabled master is in the DB."""
    import fleet_platform.workers.salt_presence_tasks as mod

    ctx = _make_db_with_masters([])
    with patch("fleet_platform.workers.salt_presence_tasks.get_sync_db", return_value=ctx):
        result = mod.sync_minion_presence()

    assert result["status"] == "skipped"
    assert "no enabled salt master" in result["reason"]


def test_sync_presence_skips_when_api_url_missing():
    """Returns 'skipped' when no enabled master has api_url configured."""
    import fleet_platform.workers.salt_presence_tasks as mod

    master = _make_master(name="mm", api_url="", api_user="admin")
    ctx = _make_db_with_masters([master])
    with patch("fleet_platform.workers.salt_presence_tasks.get_sync_db", return_value=ctx):
        result = mod.sync_minion_presence()

    assert result["status"] == "skipped"
    assert "api_url" in result["reason"]


def test_sync_presence_skips_when_api_user_missing():
    """Returns 'skipped' when no enabled master has api_user configured."""
    import fleet_platform.workers.salt_presence_tasks as mod

    master = _make_master(name="mm", api_user="")
    ctx = _make_db_with_masters([master])
    with patch("fleet_platform.workers.salt_presence_tasks.get_sync_db", return_value=ctx):
        result = mod.sync_minion_presence()

    assert result["status"] == "skipped"
    assert "api_url" in result["reason"]


# ---------------------------------------------------------------------------
# sync_minion_presence — marks nodes online
# ---------------------------------------------------------------------------


def test_sync_presence_marks_nodes_online():
    """Nodes whose minion_id appears in manage.up are set online with updated last_seen_at."""
    import fleet_platform.workers.salt_presence_tasks as mod

    master = _make_master()

    # First DB call returns the enabled masters; second returns matching nodes.
    node_a = MagicMock()
    node_a.minion_id = "mm1"
    node_a.maintenance_mode = False

    # Build two separate DB context mocks for the two get_sync_db() calls.
    scalar_master = MagicMock()
    scalar_master.scalars.return_value.all.return_value = [master]
    db_master = MagicMock()
    db_master.execute.return_value = scalar_master
    ctx_master = MagicMock()
    ctx_master.__enter__ = MagicMock(return_value=db_master)
    ctx_master.__exit__ = MagicMock(return_value=False)

    scalar_nodes = MagicMock()
    scalar_nodes.scalars.return_value.all.return_value = [node_a]
    db_nodes = MagicMock()
    db_nodes.execute.return_value = scalar_nodes
    ctx_nodes = MagicMock()
    ctx_nodes.__enter__ = MagicMock(return_value=db_nodes)
    ctx_nodes.__exit__ = MagicMock(return_value=False)

    call_count = {"n": 0}

    def db_factory():
        call_count["n"] += 1
        return ctx_master if call_count["n"] == 1 else ctx_nodes

    with (
        patch("fleet_platform.workers.salt_presence_tasks.get_sync_db", side_effect=db_factory),
        patch("fleet_platform.workers.salt_presence_tasks._runner_call", return_value=["mm1"]),
    ):
        result = mod.sync_minion_presence()

    assert result["status"] == "ok"
    assert result["online"] == 1
    assert node_a.status == "online"
    assert node_a.last_seen_at is not None


def test_sync_presence_skips_maintenance_mode_nodes():
    """Nodes in maintenance_mode are not set online."""
    import fleet_platform.workers.salt_presence_tasks as mod

    master = _make_master()

    node_m = MagicMock()
    node_m.minion_id = "mm2"
    node_m.maintenance_mode = True

    scalar_master = MagicMock()
    scalar_master.scalars.return_value.all.return_value = [master]
    db_master = MagicMock()
    db_master.execute.return_value = scalar_master
    ctx_master = MagicMock()
    ctx_master.__enter__ = MagicMock(return_value=db_master)
    ctx_master.__exit__ = MagicMock(return_value=False)

    scalar_nodes = MagicMock()
    scalar_nodes.scalars.return_value.all.return_value = [node_m]
    db_nodes = MagicMock()
    db_nodes.execute.return_value = scalar_nodes
    ctx_nodes = MagicMock()
    ctx_nodes.__enter__ = MagicMock(return_value=db_nodes)
    ctx_nodes.__exit__ = MagicMock(return_value=False)

    call_count = {"n": 0}

    def db_factory():
        call_count["n"] += 1
        return ctx_master if call_count["n"] == 1 else ctx_nodes

    with (
        patch("fleet_platform.workers.salt_presence_tasks.get_sync_db", side_effect=db_factory),
        patch("fleet_platform.workers.salt_presence_tasks._runner_call", return_value=["mm2"]),
    ):
        result = mod.sync_minion_presence()

    assert result["status"] == "ok"
    assert result["online"] == 0
    # status must NOT have been set online
    assert node_m.status != "online"


# ---------------------------------------------------------------------------
# sync_minion_presence — multi-master union (#689)
# ---------------------------------------------------------------------------


def _ctx_factory_two_phase(masters, nodes):
    """Build a get_sync_db side_effect: 1st call yields masters, 2nd yields nodes."""
    scalar_master = MagicMock()
    scalar_master.scalars.return_value.all.return_value = list(masters)
    db_master = MagicMock()
    db_master.execute.return_value = scalar_master
    ctx_master = MagicMock()
    ctx_master.__enter__ = MagicMock(return_value=db_master)
    ctx_master.__exit__ = MagicMock(return_value=False)

    scalar_nodes = MagicMock()
    scalar_nodes.scalars.return_value.all.return_value = list(nodes)
    db_nodes = MagicMock()
    db_nodes.execute.return_value = scalar_nodes
    ctx_nodes = MagicMock()
    ctx_nodes.__enter__ = MagicMock(return_value=db_nodes)
    ctx_nodes.__exit__ = MagicMock(return_value=False)

    state = {"n": 0}

    def factory():
        state["n"] += 1
        return ctx_master if state["n"] == 1 else ctx_nodes

    return factory


def test_sync_presence_unions_across_masters():
    """A minion up on the NON-default master refreshes its node (#689)."""
    import fleet_platform.workers.salt_presence_tasks as mod

    mm = _make_master(name="mm", is_default=True)
    cylon = _make_master(name="cylon", is_default=False, api_url="https://cylon.local:8080")

    # node lives on cylon (the non-default master)
    node = MagicMock()
    node.minion_id = "node-on-cylon"
    node.maintenance_mode = False

    # mm reports nobody; cylon reports the node.
    def runner_side_effect(api_url, *args, **kwargs):
        return ["node-on-cylon"] if "cylon" in api_url else []

    with (
        patch(
            "fleet_platform.workers.salt_presence_tasks.get_sync_db",
            side_effect=_ctx_factory_two_phase([mm, cylon], [node]),
        ),
        patch("fleet_platform.workers.salt_presence_tasks._runner_call", side_effect=runner_side_effect),
    ):
        result = mod.sync_minion_presence()

    assert result["status"] == "ok"
    assert result["online"] == 1
    assert result["masters"] == 2
    assert node.status == "online"
    assert node.last_seen_at is not None


def test_sync_presence_one_master_unreachable_other_works():
    """One unreachable master must not abort the sweep — the reachable one still syncs."""
    import fleet_platform.workers.salt_presence_tasks as mod

    mm = _make_master(name="mm", is_default=True)
    cylon = _make_master(name="cylon", is_default=False, api_url="https://cylon.local:8080")

    node = MagicMock()
    node.minion_id = "mm1"
    node.maintenance_mode = False

    # mm unreachable (None); cylon reachable with mm1.
    def runner_side_effect(api_url, *args, **kwargs):
        return None if "salt.local" in api_url else ["mm1"]

    with (
        patch(
            "fleet_platform.workers.salt_presence_tasks.get_sync_db",
            side_effect=_ctx_factory_two_phase([mm, cylon], [node]),
        ),
        patch("fleet_platform.workers.salt_presence_tasks._runner_call", side_effect=runner_side_effect),
    ):
        result = mod.sync_minion_presence()

    assert result["status"] == "ok"
    assert result["online"] == 1
    assert result["masters"] == 1  # only one master was reachable
    assert node.status == "online"


def test_sync_presence_error_when_all_masters_unreachable():
    """status=error when no enabled master is reachable (fleet-wide signal preserved)."""
    import fleet_platform.workers.salt_presence_tasks as mod

    mm = _make_master(name="mm", is_default=True)
    cylon = _make_master(name="cylon", is_default=False, api_url="https://cylon.local:8080")

    ctx = _make_db_with_masters([mm, cylon])
    with (
        patch("fleet_platform.workers.salt_presence_tasks.get_sync_db", return_value=ctx),
        patch("fleet_platform.workers.salt_presence_tasks._runner_call", return_value=None),
    ):
        result = mod.sync_minion_presence()

    assert result["status"] == "error"
    assert "reachable" in result["reason"]


# ---------------------------------------------------------------------------
# Beat schedule registration
# ---------------------------------------------------------------------------


def test_sync_presence_in_beat_schedule():
    """sync-minion-presence must be registered in the celery beat schedule."""
    from fleet_platform.workers.celery_app import celery_app

    schedule = celery_app.conf.beat_schedule
    assert "sync-minion-presence" in schedule
    task = schedule["sync-minion-presence"]["task"]
    assert "salt_presence" in task
    assert schedule["sync-minion-presence"]["schedule"] <= 120  # runs at least every 2 min
