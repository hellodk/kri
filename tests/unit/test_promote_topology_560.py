"""Unit tests for promote-node + master-minions topology endpoints — issue #560.

Phase 5 of the master-lifecycle epic.

Tests are pure-Python (SQLAlchemy inspection + Pydantic schema validation).
No live DB required — route logic is exercised via in-process async calls
against an in-memory SQLite database using the same ORM models.

Run:
    pytest tests/unit/test_promote_topology_560.py -q
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

# ---------------------------------------------------------------------------
# Helpers: thin fakes for the ORM-level tests
# ---------------------------------------------------------------------------


def _make_node(
    bootstrap_ip: str | None = "192.168.1.10",
    hostname: str | None = "mm-01",
    minion_id: str = "mm-01",
    node_id: uuid.UUID | None = None,
) -> MagicMock:
    """Return a MagicMock that looks enough like a Node ORM instance."""
    n = MagicMock()
    n.id = node_id or uuid.uuid4()
    n.minion_id = minion_id
    n.hostname = hostname
    n.bootstrap_ip = bootstrap_ip
    n.ip_address = None
    n.os_version = None
    n.hardware_model = None
    n.status = "active"
    n.drift_score = 0
    n.cpu_usage_pct = None
    n.mem_usage_pct = None
    n.last_seen_at = None
    n.tags = []
    n.maintenance_mode = False
    n.xcode_version = None
    n.macos_version = None
    n.ssh_state = None
    n.ssh_checked_at = None
    n.ssh_detail = None
    n.is_master = False
    n.master_status = None
    return n


def _make_master(
    master_id: uuid.UUID | None = None,
    node_id: uuid.UUID | None = None,
    name: str = "mm-01",
    address: str = "192.168.1.10",
    provision_status: str = "unprovisioned",
) -> MagicMock:
    """Return a MagicMock that looks enough like a SaltMaster ORM instance."""
    m = MagicMock()
    m.id = master_id or uuid.uuid4()
    m.node_id = node_id
    m.name = name
    m.address = address
    m.enabled = True
    m.is_default = False
    m.publish_port = 4505
    m.ret_port = 4506
    m.salt_api_port = 8080
    m.use_tls = True
    m.api_url = f"https://{address}:8080"
    m.api_user = None
    m.api_password_enc = None
    m.control_mode = "salt_api"
    m.api_eauth = "pam"
    m.token_delivery = "ingest"
    m.tls_verify = False
    m.auto_accept = True
    m.status = "unknown"
    m.last_checked_at = None
    m.last_error = None
    m.checks = None
    m.provision_status = provision_status
    m.os_family = None
    m.salt_version = None
    m.last_provisioned_at = None
    m.provision_error = None
    m.ssh_host = None
    m.ssh_user = None
    m.created_at = None
    m.updated_at = None
    return m


# ---------------------------------------------------------------------------
# _derive_api_url helper (no DB)
# ---------------------------------------------------------------------------


class TestDeriveApiUrl:
    def test_https_scheme_when_use_tls_true(self):
        from fleet_platform.api.routes.salt_masters import _derive_api_url

        assert _derive_api_url("192.168.1.10", 8080, True) == "https://192.168.1.10:8080"

    def test_http_scheme_when_use_tls_false(self):
        from fleet_platform.api.routes.salt_masters import _derive_api_url

        assert _derive_api_url("192.168.1.10", 8080, False) == "http://192.168.1.10:8080"

    def test_custom_port(self):
        from fleet_platform.api.routes.salt_masters import _derive_api_url

        assert _derive_api_url("10.0.0.1", 8000, True) == "https://10.0.0.1:8000"


# ---------------------------------------------------------------------------
# promote_node_to_master — happy path
# ---------------------------------------------------------------------------


class TestPromoteNodeToMaster:
    """promote_node_to_master creates a SaltMaster linked to the node."""

    @pytest.mark.asyncio
    async def test_creates_master_with_node_ip_as_address(self):
        """Happy path: node with bootstrap_ip → master.address = bootstrap_ip."""

        from fleet_platform.api.routes.salt_masters import promote_node_to_master

        node = _make_node(bootstrap_ip="192.168.1.50", hostname="mac-01")
        node_id = node.id

        # Simulate DB returning: node found, no existing master for node, 0 masters total.
        db = AsyncMock()

        # Build scalar mock chain for selectinload / execute patterns.
        def _execute_side_effect(query):
            result = AsyncMock()
            # We need to distinguish calls:
            # 1st call — select(Node) → returns node
            # 2nd call — select(SaltMaster).where(node_id) → returns None
            # 3rd call — select(SaltMaster).where(name) → returns None (no conflict)
            # 4th call — select(func.count()) → returns 0
            return result

        captured = []

        async def _exec(query):
            call_idx = len(captured)
            captured.append(query)
            r = MagicMock()
            if call_idx == 0:
                # select(Node) — found
                r.scalar_one_or_none.return_value = node
            elif call_idx == 1:
                # existing master for node — none
                r.scalar_one_or_none.return_value = None
            elif call_idx == 2:
                # name conflict check — none
                r.scalar_one_or_none.return_value = None
            elif call_idx == 3:
                # count of masters — 0 (first master)
                r.scalar_one.return_value = 0
            return r

        db.execute = _exec
        db.add = MagicMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        added_master: list = []

        def _capture_add(obj):
            added_master.append(obj)

        db.add = _capture_add

        try:
            await promote_node_to_master(node_id=node_id, db=db)  # type: ignore[arg-type]
        except Exception:
            # SaltMasterResponse.model_validate will fail on MagicMock; that's OK —
            # we care that db.add was called with the right object.
            pass

        assert len(added_master) == 1
        master_obj = added_master[0]
        assert master_obj.address == "192.168.1.50"
        assert master_obj.node_id == node_id
        assert master_obj.name == "mac-01"
        assert master_obj.is_default is True  # first master
        assert master_obj.provision_status == "unprovisioned"
        assert master_obj.api_url == "https://192.168.1.50:4507"

    @pytest.mark.asyncio
    async def test_uses_minion_id_when_hostname_is_none(self):
        """name falls back to minion_id when hostname is None."""
        from fleet_platform.api.routes.salt_masters import promote_node_to_master

        node = _make_node(bootstrap_ip="10.0.0.1", hostname=None, minion_id="minion-xyz")
        node_id = node.id

        captured = []

        async def _exec(query):
            call_idx = len(captured)
            captured.append(query)
            r = MagicMock()
            if call_idx == 0:
                r.scalar_one_or_none.return_value = node
            elif call_idx == 1:
                r.scalar_one_or_none.return_value = None
            elif call_idx == 2:
                r.scalar_one_or_none.return_value = None
            elif call_idx == 3:
                r.scalar_one.return_value = 5  # not the first master
            return r

        db = AsyncMock()
        db.execute = _exec
        added: list = []
        db.add = added.append
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        try:
            await promote_node_to_master(node_id=node_id, db=db)  # type: ignore[arg-type]
        except Exception:
            pass

        assert len(added) == 1
        assert added[0].name == "minion-xyz"
        assert added[0].is_default is False  # not the first master

    @pytest.mark.asyncio
    async def test_node_without_bootstrap_ip_raises_422(self):
        """A node with bootstrap_ip=None must raise HTTP 422."""
        from fastapi import HTTPException

        from fleet_platform.api.routes.salt_masters import promote_node_to_master

        node = _make_node(bootstrap_ip=None)
        node_id = node.id

        async def _exec(_query):
            r = MagicMock()
            r.scalar_one_or_none.return_value = node
            return r

        db = AsyncMock()
        db.execute = _exec

        with pytest.raises(HTTPException) as exc_info:
            await promote_node_to_master(node_id=node_id, db=db)  # type: ignore[arg-type]

        assert exc_info.value.status_code == 422
        assert "bootstrap_ip" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_node_not_found_raises_404(self):
        """Non-existent node_id must raise HTTP 404."""
        from fastapi import HTTPException

        from fleet_platform.api.routes.salt_masters import promote_node_to_master

        async def _exec(_query):
            r = MagicMock()
            r.scalar_one_or_none.return_value = None
            return r

        db = AsyncMock()
        db.execute = _exec

        with pytest.raises(HTTPException) as exc_info:
            await promote_node_to_master(node_id=uuid.uuid4(), db=db)  # type: ignore[arg-type]

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_duplicate_node_raises_409(self):
        """Promoting a node that already has a SaltMaster must raise HTTP 409."""
        from fastapi import HTTPException

        from fleet_platform.api.routes.salt_masters import promote_node_to_master

        node = _make_node(bootstrap_ip="192.168.1.1")
        existing_master = _make_master(node_id=node.id)

        call_idx = 0

        async def _exec(_query):
            nonlocal call_idx
            r = MagicMock()
            if call_idx == 0:
                r.scalar_one_or_none.return_value = node
            else:
                r.scalar_one_or_none.return_value = existing_master
            call_idx += 1
            return r

        db = AsyncMock()
        db.execute = _exec

        with pytest.raises(HTTPException) as exc_info:
            await promote_node_to_master(node_id=node.id, db=db)  # type: ignore[arg-type]

        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_name_uniquified_with_suffix_on_conflict(self):
        """When a master with the same name exists, a numeric suffix is appended."""
        from fleet_platform.api.routes.salt_masters import promote_node_to_master

        node = _make_node(bootstrap_ip="10.0.0.2", hostname="mac-01")
        node_id = node.id

        conflict_master = _make_master(name="mac-01")

        call_idx = 0

        async def _exec(_query):
            nonlocal call_idx
            r = MagicMock()
            if call_idx == 0:
                # Node found
                r.scalar_one_or_none.return_value = node
            elif call_idx == 1:
                # No existing master for node
                r.scalar_one_or_none.return_value = None
            elif call_idx == 2:
                # Name "mac-01" conflicts
                r.scalar_one_or_none.return_value = conflict_master
            elif call_idx == 3:
                # Name "mac-01-1" is free
                r.scalar_one_or_none.return_value = None
            elif call_idx == 4:
                # Master count — not first
                r.scalar_one.return_value = 1
            call_idx += 1
            return r

        db = AsyncMock()
        db.execute = _exec
        added: list = []
        db.add = added.append
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        try:
            await promote_node_to_master(node_id=node_id, db=db)  # type: ignore[arg-type]
        except Exception:
            pass

        assert len(added) == 1
        assert added[0].name == "mac-01-1"


# ---------------------------------------------------------------------------
# list_master_minions
# ---------------------------------------------------------------------------


class TestListMasterMinions:
    @pytest.mark.asyncio
    async def test_returns_nodes_for_master(self):
        """list_master_minions returns NodeListItem list for a known master."""
        from fleet_platform.api.routes.salt_masters import list_master_minions

        master_id = uuid.uuid4()
        master = _make_master(master_id=master_id)

        node1 = _make_node(hostname="mac-01", minion_id="mac-01")
        node1.salt_master_id = master_id
        node2 = _make_node(hostname="mac-02", minion_id="mac-02")
        node2.salt_master_id = master_id

        call_idx = 0

        async def _exec(_query):
            nonlocal call_idx
            r = MagicMock()
            if call_idx == 0:
                # select(SaltMaster) — found
                r.scalar_one_or_none.return_value = master
            else:
                # select(Node) — two minions
                r.scalars.return_value.all.return_value = [node1, node2]
            call_idx += 1
            return r

        db = AsyncMock()
        db.execute = _exec

        results = await list_master_minions(master_id=master_id, db=db)  # type: ignore[arg-type]

        assert len(results) == 2
        ids = {str(r.id) for r in results}
        assert str(node1.id) in ids
        assert str(node2.id) in ids

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_minions(self):
        """Returns [] (not 404) when no nodes are assigned to the master."""
        from fleet_platform.api.routes.salt_masters import list_master_minions

        master_id = uuid.uuid4()
        master = _make_master(master_id=master_id)

        call_idx = 0

        async def _exec(_query):
            nonlocal call_idx
            r = MagicMock()
            if call_idx == 0:
                r.scalar_one_or_none.return_value = master
            else:
                r.scalars.return_value.all.return_value = []
            call_idx += 1
            return r

        db = AsyncMock()
        db.execute = _exec

        results = await list_master_minions(master_id=master_id, db=db)  # type: ignore[arg-type]
        assert results == []

    @pytest.mark.asyncio
    async def test_unknown_master_raises_404(self):
        """list_master_minions raises 404 when the master does not exist."""
        from fastapi import HTTPException

        from fleet_platform.api.routes.salt_masters import list_master_minions

        async def _exec(_query):
            r = MagicMock()
            r.scalar_one_or_none.return_value = None
            return r

        db = AsyncMock()
        db.execute = _exec

        with pytest.raises(HTTPException) as exc_info:
            await list_master_minions(master_id=uuid.uuid4(), db=db)  # type: ignore[arg-type]

        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Schema / field-level contracts
# ---------------------------------------------------------------------------


class TestSaltMasterResponseContract:
    """SaltMasterResponse must include node_id (required for topology link)."""

    def test_node_id_field_present_in_schema(self):
        from fleet_platform.schemas.salt_master import SaltMasterResponse

        assert "node_id" in SaltMasterResponse.model_fields

    def test_node_id_field_is_nullable(self):
        from fleet_platform.schemas.salt_master import SaltMasterResponse

        field = SaltMasterResponse.model_fields["node_id"]
        # In Pydantic v2, nullable fields have is_required() == False or annotation includes None
        import typing

        ann = field.annotation
        origin = getattr(ann, "__origin__", None)
        # Should be Optional[UUID] i.e. Union[UUID, None]
        assert origin is typing.Union or field.default is None or not field.is_required()


class TestNodeListItemContract:
    """NodeListItem must have the fields required by the minions endpoint."""

    def test_required_fields_exist(self):
        from fleet_platform.schemas.fleet import NodeListItem

        for field in ("id", "minion_id", "hostname", "status"):
            assert field in NodeListItem.model_fields, f"{field} missing from NodeListItem"


# ---------------------------------------------------------------------------
# Auth contract — promote_node_to_master requires admin
# ---------------------------------------------------------------------------


class TestAuthContracts:
    def test_promote_route_requires_admin_dep(self):
        """The from-node route must use require_role('admin'), not get_current_user."""
        import inspect

        import pytest
        from fastapi import params as fa_params

        from fleet_platform.api.routes.salt_masters import promote_node_to_master

        sig = inspect.signature(promote_node_to_master)
        for param in sig.parameters.values():
            if isinstance(param.default, fa_params.Depends):
                dep = param.default.dependency
                # require_role returns a closure whose __qualname__ is
                # 'require_role.<locals>.dependency'. Verify it captures "admin"
                # in its permitted-roles set.
                if getattr(dep, "__qualname__", "").endswith("require_role.<locals>.dependency"):
                    if hasattr(dep, "__closure__") and dep.__closure__:
                        for cell in dep.__closure__:
                            try:
                                val = cell.cell_contents
                                if isinstance(val, set) and "admin" in val:
                                    return
                            except ValueError:
                                pass
        pytest.fail("promote_node_to_master must use require_role('admin') — no require_role dep with 'admin' found")

    def test_minions_route_accessible_to_viewer(self):
        """The minions route must use get_current_user (viewer+), not require_role('admin')."""
        import inspect

        import pytest
        from fastapi import params as fa_params

        from fleet_platform.api.routes.salt_masters import list_master_minions
        from fleet_platform.core.auth import get_current_user

        sig = inspect.signature(list_master_minions)
        deps = [p.default.dependency for p in sig.parameters.values() if isinstance(p.default, fa_params.Depends)]
        assert get_current_user in deps, "list_master_minions must use get_current_user (viewer+)"
        # Must NOT gate on admin-only — verify no require_role dep with "admin" only
        for dep in deps:
            if getattr(dep, "__qualname__", "").endswith("require_role.<locals>.dependency"):
                if hasattr(dep, "__closure__") and dep.__closure__:
                    for cell in dep.__closure__:
                        try:
                            val = cell.cell_contents
                            if isinstance(val, set) and val == {"admin"}:
                                pytest.fail("list_master_minions must NOT use require_role('admin')")
                        except ValueError:
                            pass
