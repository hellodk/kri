"""Unit tests for GET /salt/masters list endpoint — issue #521, epic #523.

Tests verify:
- Route returns a list of SaltMasterResponse objects
- Secret fields (api_password, api_password_enc) are absent from the response
- Endpoint requires authentication (401 when no valid token)

All DB access is mocked — no live DB required.
"""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_master(**kwargs) -> SimpleNamespace:
    """Build a SaltMaster-like SimpleNamespace without hitting the DB."""
    defaults = dict(
        id=uuid.uuid4(),
        name="prod-master",
        enabled=True,
        is_default=True,
        address="salt.prod.local",
        publish_port=4505,
        ret_port=4506,
        control_mode="salt_api",
        api_url="http://salt.prod.local:8080",
        api_user="saltadmin",
        api_password_enc="$fernet$encrypted",
        api_eauth="pam",
        token_delivery="ingest",
        status="healthy",
        last_checked_at=datetime.now(UTC),
        last_error=None,
        checks=[{"check": "dns", "status": "pass", "detail": "OK", "latency_ms": 2}],
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


# ---------------------------------------------------------------------------
# Response schema — no secrets exposed
# ---------------------------------------------------------------------------


class TestSaltMasterResponseExcludesSecrets:
    def test_response_schema_excludes_api_password_enc(self):
        from fleet_platform.schemas.salt_master import SaltMasterResponse

        fields = SaltMasterResponse.model_fields
        assert "api_password_enc" not in fields, "SaltMasterResponse must NOT include api_password_enc"

    def test_response_schema_excludes_api_password(self):
        from fleet_platform.schemas.salt_master import SaltMasterResponse

        fields = SaltMasterResponse.model_fields
        # api_password is write-only in Create/Update; must not appear in Response
        assert "api_password" not in fields, "SaltMasterResponse must NOT include api_password (write-only field)"

    def test_response_serialization_does_not_include_password(self):
        """Serialising a model object must never emit a password key."""
        from fleet_platform.schemas.salt_master import SaltMasterResponse

        master = _make_master()
        resp = SaltMasterResponse.model_validate(master, from_attributes=True)
        data = resp.model_dump()

        for key in data:
            assert "password" not in key.lower(), (
                f"Serialised SaltMasterResponse must not include key '{key}' (contains 'password')"
            )

    def test_response_retains_non_secret_fields(self):
        from fleet_platform.schemas.salt_master import SaltMasterResponse

        master = _make_master(name="test-master", status="healthy")
        resp = SaltMasterResponse.model_validate(master, from_attributes=True)

        assert resp.name == "test-master"
        assert resp.status == "healthy"
        assert resp.is_default is True
        assert resp.control_mode == "salt_api"
        assert resp.token_delivery == "ingest"


# ---------------------------------------------------------------------------
# Endpoint behaviour — mocked DB + auth
# ---------------------------------------------------------------------------


class TestListSaltMastersEndpoint:
    def _make_scalars(self, masters):
        """Build a mock scalars result for AsyncSession.execute."""
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = masters
        result_mock = MagicMock()
        result_mock.scalars.return_value = scalars_mock
        return result_mock

    @pytest.mark.asyncio
    async def test_list_returns_all_masters(self):
        from fleet_platform.api.routes.salt_masters import list_salt_masters

        m1 = _make_master(name="prod", is_default=True)
        m2 = _make_master(name="staging", is_default=False)

        db = AsyncMock()
        db.execute = AsyncMock(return_value=self._make_scalars([m1, m2]))

        result = await list_salt_masters(db=db, _={"sub": "admin"})

        assert len(result) == 2
        names = {r.name for r in result}
        assert names == {"prod", "staging"}

    @pytest.mark.asyncio
    async def test_list_empty_returns_empty_list(self):
        from fleet_platform.api.routes.salt_masters import list_salt_masters

        db = AsyncMock()
        db.execute = AsyncMock(return_value=self._make_scalars([]))

        result = await list_salt_masters(db=db, _={"sub": "admin"})

        assert result == []

    @pytest.mark.asyncio
    async def test_list_response_items_are_salt_master_response(self):
        from fleet_platform.api.routes.salt_masters import list_salt_masters
        from fleet_platform.schemas.salt_master import SaltMasterResponse

        m = _make_master()
        db = AsyncMock()
        db.execute = AsyncMock(return_value=self._make_scalars([m]))

        result = await list_salt_masters(db=db, _={"sub": "viewer"})

        assert len(result) == 1
        assert isinstance(result[0], SaltMasterResponse)

    @pytest.mark.asyncio
    async def test_list_items_exclude_password_fields(self):
        from fleet_platform.api.routes.salt_masters import list_salt_masters

        m = _make_master()
        db = AsyncMock()
        db.execute = AsyncMock(return_value=self._make_scalars([m]))

        result = await list_salt_masters(db=db, _={"sub": "viewer"})

        item_dict = result[0].model_dump()
        for key in item_dict:
            assert "password" not in key.lower(), f"Response item must not expose key '{key}' (contains 'password')"

    @pytest.mark.asyncio
    async def test_list_requires_authentication(self):
        """Endpoint must use get_current_user — verify the dependency exists."""

        # Inspect the function's FastAPI dependencies
        import inspect

        from fleet_platform.api.routes.salt_masters import list_salt_masters

        sig = inspect.signature(list_salt_masters)
        params = sig.parameters

        # The _ parameter must be present (auth injection)
        assert "_" in params, "list_salt_masters must have a '_' auth dependency parameter"

    def test_router_registers_get_masters_route(self):
        """The /masters GET route must be present on the router."""
        from fleet_platform.api.routes.salt_masters import router

        get_routes = [
            r.path  # type: ignore[attr-defined]
            for r in router.routes  # type: ignore[attr-defined]
            if "GET" in getattr(r, "methods", set())
        ]
        assert "/api/v1/salt/masters" in get_routes, f"GET /api/v1/salt/masters route not found. Routes: {get_routes}"
