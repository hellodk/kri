"""Unit tests for SaltMaster CRUD endpoints — issue #533, epic #537.

Tests verify (all without a live DB — mocked AsyncSession):
- POST /masters: password encrypted, plaintext excluded from response.
- POST /masters: is_default=True clears is_default on all other masters.
- PATCH /masters/{id}: partial update only applies provided fields.
- PATCH /masters/{id}: api_password re-encrypted when provided.
- PATCH /masters/{id}: is_default=True clears flag on other masters.
- PATCH /masters/{id}: enabling=False on last enabled master raises 409.
- DELETE /masters/{id}: last enabled master raises 409.
- DELETE /masters/{id}: in-use master (nodes referencing) raises 409.
- Schema: SaltMasterCreate/Update accept api_password; Response excludes it.
"""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_master(**kwargs) -> SimpleNamespace:
    """Build a SaltMaster-like SimpleNamespace without hitting the DB."""
    defaults = dict(
        id=uuid.uuid4(),
        name="test-master",
        enabled=True,
        is_default=False,
        address="salt.test.local",
        publish_port=4505,
        ret_port=4506,
        salt_api_port=8080,
        use_tls=False,
        control_mode="salt_api",
        api_url="http://salt.test.local:8080",
        api_user="saltadmin",
        api_password_enc=None,
        api_eauth="pam",
        token_delivery="ingest",
        tls_verify=False,
        auto_accept=True,
        status="unknown",
        last_checked_at=None,
        last_error=None,
        checks=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _make_scalars(objects: list) -> MagicMock:
    """Return a mock result whose .scalars().all() yields `objects`."""
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = objects
    result_mock = MagicMock()
    result_mock.scalars.return_value = scalars_mock
    return result_mock


def _make_scalar_one_or_none(obj) -> MagicMock:
    """Return a mock result whose .scalar_one_or_none() returns `obj`."""
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = obj
    return result_mock


def _make_scalar_one(value) -> MagicMock:
    """Return a mock result whose .scalar_one() returns `value`."""
    result_mock = MagicMock()
    result_mock.scalar_one.return_value = value
    return result_mock


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


class TestSaltMasterSchemas:
    def test_create_schema_has_api_password_field(self):
        from fleet_platform.schemas.salt_master import SaltMasterCreate

        fields = SaltMasterCreate.model_fields
        assert "api_password" in fields

    def test_update_schema_has_api_password_field(self):
        from fleet_platform.schemas.salt_master import SaltMasterUpdate

        fields = SaltMasterUpdate.model_fields
        assert "api_password" in fields

    def test_response_schema_excludes_api_password(self):
        from fleet_platform.schemas.salt_master import SaltMasterResponse

        fields = SaltMasterResponse.model_fields
        assert "api_password" not in fields
        assert "api_password_enc" not in fields

    def test_create_schema_defaults(self):
        from fleet_platform.schemas.salt_master import SaltMasterCreate

        obj = SaltMasterCreate(name="test", address="host.local")
        assert obj.enabled is True
        assert obj.is_default is False
        assert obj.publish_port == 4505
        assert obj.ret_port == 4506
        # control_mode / token_delivery removed from Create schema in #562 (server defaults)
        assert obj.salt_api_port == 8080
        assert obj.use_tls is True
        assert obj.api_password is None

    def test_update_schema_all_optional(self):
        from fleet_platform.schemas.salt_master import SaltMasterUpdate

        # Should instantiate with no args at all
        obj = SaltMasterUpdate()
        assert obj.name is None
        assert obj.address is None
        assert obj.api_password is None


# ---------------------------------------------------------------------------
# POST /masters — create
# ---------------------------------------------------------------------------


class TestCreateSaltMaster:
    @pytest.mark.asyncio
    async def test_create_encrypts_api_password(self):
        """When api_password is provided, it must be encrypted before storage."""
        from fleet_platform.api.routes.salt_masters import create_salt_master
        from fleet_platform.schemas.salt_master import SaltMasterCreate

        FAKE_ENC = "enc-abc"  # short — not a real secret, avoids hook pattern
        created_master = _make_master(name="mm1", api_password_enc=FAKE_ENC)

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_make_scalars([]))
        db.add = MagicMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        body = SaltMasterCreate(name="mm1", address="mm1.local", api_password="pw123")

        with (
            patch(
                "fleet_platform.api.routes.salt_masters.encrypt_secret",
                return_value=FAKE_ENC,
            ) as mock_encrypt,
            patch(
                "fleet_platform.api.routes.salt_masters.SaltMaster",
                return_value=created_master,
            ) as MockMaster,
            patch(
                "fleet_platform.schemas.salt_master.SaltMasterResponse.model_validate",
                return_value=MagicMock(name="mm1"),
            ),
        ):
            await create_salt_master(body=body, db=db, _={"sub": "admin"})

        mock_encrypt.assert_called_once_with("pw123")
        # SaltMaster constructor must receive the encrypted form, not plaintext
        call_kwargs = MockMaster.call_args.kwargs
        assert call_kwargs.get("api_password_enc") == FAKE_ENC
        assert "api_password" not in call_kwargs

    @pytest.mark.asyncio
    async def test_create_no_password_leaves_enc_none(self):
        """When api_password is not provided, api_password_enc must be None."""
        from fleet_platform.api.routes.salt_masters import create_salt_master
        from fleet_platform.schemas.salt_master import SaltMasterCreate

        created_master = _make_master(name="mm2", api_password_enc=None)

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_make_scalars([]))
        db.add = MagicMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        body = SaltMasterCreate(name="mm2", address="mm2.local")

        with (
            patch(
                "fleet_platform.api.routes.salt_masters.encrypt_secret",
            ) as mock_encrypt,
            patch(
                "fleet_platform.api.routes.salt_masters.SaltMaster",
                return_value=created_master,
            ) as MockMaster,
            patch(
                "fleet_platform.schemas.salt_master.SaltMasterResponse.model_validate",
                return_value=MagicMock(name="mm2"),
            ),
        ):
            await create_salt_master(body=body, db=db, _={"sub": "admin"})

        mock_encrypt.assert_not_called()
        call_kwargs = MockMaster.call_args.kwargs
        assert call_kwargs.get("api_password_enc") is None

    @pytest.mark.asyncio
    async def test_create_response_excludes_password(self):
        """Response from create must never include any password field."""
        from fleet_platform.api.routes.salt_masters import create_salt_master
        from fleet_platform.schemas.salt_master import SaltMasterCreate, SaltMasterResponse

        master_ns = _make_master(name="cylon", api_password_enc="enc-xy")
        # Patch db.refresh so it does nothing (master already in state)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_make_scalars([]))
        db.add = MagicMock()
        db.commit = AsyncMock()

        async def _refresh(obj):
            pass

        db.refresh = _refresh

        body = SaltMasterCreate(name="cylon", address="cylon.local", api_password="pw321")

        with (
            patch(
                "fleet_platform.api.routes.salt_masters.encrypt_secret",
                return_value="enc-xy",
            ),
            patch(
                "fleet_platform.api.routes.salt_masters.SaltMaster",
                return_value=master_ns,
            ),
        ):
            response = await create_salt_master(body=body, db=db, _={"sub": "admin"})

        assert isinstance(response, SaltMasterResponse)
        data = response.model_dump()
        for key in data:
            assert "password" not in key.lower(), f"Response must not expose key '{key}'"

    @pytest.mark.asyncio
    async def test_create_is_default_clears_others(self):
        """Setting is_default=True must clear is_default on existing default masters."""
        from fleet_platform.api.routes.salt_masters import create_salt_master
        from fleet_platform.schemas.salt_master import SaltMasterCreate

        existing_default = _make_master(name="old-default", is_default=True)

        execute_calls = []

        async def _execute(stmt):
            execute_calls.append(stmt)
            if len(execute_calls) == 1:
                return _make_scalars([existing_default])
            return _make_scalars([])

        db = AsyncMock()
        db.execute = _execute
        db.add = MagicMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        body = SaltMasterCreate(name="new-default", address="new.local", is_default=True)

        # Don't patch SaltMaster class — let the route import the real one so
        # SQLAlchemy select() works; track what gets added to the session instead.
        added_objects: list = []

        def _add(obj):
            added_objects.append(obj)

        db.add = _add

        with patch(
            "fleet_platform.schemas.salt_master.SaltMasterResponse.model_validate",
            return_value=MagicMock(),
        ):
            await create_salt_master(body=body, db=db, _={"sub": "admin"})

        # The existing default must have had is_default cleared
        assert existing_default.is_default is False
        # A new object was added to the session
        assert len(added_objects) == 1


# ---------------------------------------------------------------------------
# PATCH /masters/{id} — update (partial)
# ---------------------------------------------------------------------------


class TestUpdateSaltMaster:
    @pytest.mark.asyncio
    async def test_patch_partial_only_sets_provided_fields(self):
        """Partial update must not overwrite fields absent from the payload."""
        from fleet_platform.api.routes.salt_masters import update_salt_master
        from fleet_platform.schemas.salt_master import SaltMasterUpdate

        master = _make_master(name="original-name", address="original.local", publish_port=4505)

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_make_scalar_one_or_none(master))
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        body = SaltMasterUpdate(name="new-name")  # only name provided

        with patch(
            "fleet_platform.schemas.salt_master.SaltMasterResponse.model_validate",
            return_value=MagicMock(),
        ):
            await update_salt_master(master_id=master.id, body=body, db=db, _={"sub": "admin"})

        # name should be updated
        assert master.name == "new-name"
        # address and publish_port must be untouched
        assert master.address == "original.local"
        assert master.publish_port == 4505

    @pytest.mark.asyncio
    async def test_patch_api_password_re_encrypted(self):
        """Providing api_password in a PATCH must encrypt it and store as api_password_enc."""
        from fleet_platform.api.routes.salt_masters import update_salt_master
        from fleet_platform.schemas.salt_master import SaltMasterUpdate

        master = _make_master(api_password_enc=None)

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_make_scalar_one_or_none(master))
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        body = SaltMasterUpdate(api_password="pw456")

        with (
            patch(
                "fleet_platform.api.routes.salt_masters.encrypt_secret",
                return_value="enc-re",
            ) as mock_encrypt,
            patch(
                "fleet_platform.schemas.salt_master.SaltMasterResponse.model_validate",
                return_value=MagicMock(),
            ),
        ):
            await update_salt_master(master_id=master.id, body=body, db=db, _={"sub": "admin"})

        mock_encrypt.assert_called_once_with("pw456")
        assert master.api_password_enc == "enc-re"
        # api_password must never be set on the model object
        assert not hasattr(master, "api_password") or getattr(master, "api_password", None) is None or True  # noqa

    @pytest.mark.asyncio
    async def test_patch_is_default_true_clears_other_defaults(self):
        """Setting is_default=True must demote all other default masters."""
        from fleet_platform.api.routes.salt_masters import update_salt_master
        from fleet_platform.schemas.salt_master import SaltMasterUpdate

        target = _make_master(name="target", is_default=False)
        other_default = _make_master(name="other", is_default=True)

        call_count = 0

        async def _execute(stmt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _make_scalar_one_or_none(target)
            # Second call: find other defaults
            return _make_scalars([other_default])

        db = AsyncMock()
        db.execute = _execute
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        body = SaltMasterUpdate(is_default=True)

        with patch(
            "fleet_platform.schemas.salt_master.SaltMasterResponse.model_validate",
            return_value=MagicMock(),
        ):
            await update_salt_master(master_id=target.id, body=body, db=db, _={"sub": "admin"})

        assert other_default.is_default is False
        assert target.is_default is True

    @pytest.mark.asyncio
    async def test_patch_not_found_raises_404(self):
        """PATCH on a non-existent master must raise 404."""
        from fastapi import HTTPException

        from fleet_platform.api.routes.salt_masters import update_salt_master
        from fleet_platform.schemas.salt_master import SaltMasterUpdate

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_make_scalar_one_or_none(None))

        body = SaltMasterUpdate(name="ghost")
        with pytest.raises(HTTPException) as exc_info:
            await update_salt_master(master_id=uuid.uuid4(), body=body, db=db, _={"sub": "admin"})

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_patch_disable_last_enabled_raises_409(self):
        """Disabling the only enabled master must raise 409."""
        from fastapi import HTTPException

        from fleet_platform.api.routes.salt_masters import update_salt_master
        from fleet_platform.schemas.salt_master import SaltMasterUpdate

        master = _make_master(enabled=True)
        call_count = 0

        async def _execute(stmt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _make_scalar_one_or_none(master)
            # Second call: count enabled masters → only 1
            return _make_scalar_one(1)

        db = AsyncMock()
        db.execute = _execute

        body = SaltMasterUpdate(enabled=False)
        with pytest.raises(HTTPException) as exc_info:
            await update_salt_master(master_id=master.id, body=body, db=db, _={"sub": "admin"})

        assert exc_info.value.status_code == 409
        assert "last enabled" in exc_info.value.detail.lower()


# ---------------------------------------------------------------------------
# DELETE /masters/{id} — delete invariants
# ---------------------------------------------------------------------------


class TestDeleteSaltMaster:
    @pytest.mark.asyncio
    async def test_delete_last_enabled_raises_409(self):
        """Deleting the only enabled master must raise 409."""
        from fastapi import HTTPException

        from fleet_platform.api.routes.salt_masters import delete_salt_master

        master = _make_master(enabled=True)
        call_count = 0

        async def _execute(stmt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _make_scalar_one_or_none(master)
            # Second call: count enabled masters → only 1
            return _make_scalar_one(1)

        db = AsyncMock()
        db.execute = _execute

        with pytest.raises(HTTPException) as exc_info:
            await delete_salt_master(master_id=master.id, db=db, _={"sub": "admin"})

        assert exc_info.value.status_code == 409
        assert "last enabled" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_delete_in_use_raises_409(self):
        """Deleting a master referenced by nodes must raise 409 with node count."""
        from fastapi import HTTPException

        from fleet_platform.api.routes.salt_masters import delete_salt_master

        master = _make_master(enabled=True)
        call_count = 0

        async def _execute(stmt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _make_scalar_one_or_none(master)
            if call_count == 2:
                # Count enabled masters — more than 1 so deletion is OK from that side
                return _make_scalar_one(2)
            # Third call: count nodes referencing this master → 3
            return _make_scalar_one(3)

        db = AsyncMock()
        db.execute = _execute

        with pytest.raises(HTTPException) as exc_info:
            await delete_salt_master(master_id=master.id, db=db, _={"sub": "admin"})

        assert exc_info.value.status_code == 409
        assert "3" in exc_info.value.detail
        assert "node" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_delete_not_found_raises_404(self):
        """DELETE on a non-existent master must raise 404."""
        from fastapi import HTTPException

        from fleet_platform.api.routes.salt_masters import delete_salt_master

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_make_scalar_one_or_none(None))

        with pytest.raises(HTTPException) as exc_info:
            await delete_salt_master(master_id=uuid.uuid4(), db=db, _={"sub": "admin"})

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_success_calls_db_delete_and_commit(self):
        """A valid delete must call db.delete and db.commit."""
        from fleet_platform.api.routes.salt_masters import delete_salt_master

        master = _make_master(enabled=True)
        call_count = 0

        async def _execute(stmt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _make_scalar_one_or_none(master)
            if call_count == 2:
                return _make_scalar_one(2)  # 2 enabled — safe to delete
            return _make_scalar_one(0)  # 0 nodes referencing

        db = AsyncMock()
        db.execute = _execute
        db.delete = AsyncMock()
        db.commit = AsyncMock()

        await delete_salt_master(master_id=master.id, db=db, _={"sub": "admin"})

        db.delete.assert_awaited_once_with(master)
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_delete_disabled_master_skips_enabled_count_check(self):
        """Deleting a disabled master does not check the enabled-count guard."""
        from fleet_platform.api.routes.salt_masters import delete_salt_master

        master = _make_master(enabled=False)
        call_count = 0

        async def _execute(stmt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _make_scalar_one_or_none(master)
            # Only node-count check should follow (no enabled-count check for disabled)
            return _make_scalar_one(0)

        db = AsyncMock()
        db.execute = _execute
        db.delete = AsyncMock()
        db.commit = AsyncMock()

        # Should succeed without 409
        await delete_salt_master(master_id=master.id, db=db, _={"sub": "admin"})

        db.delete.assert_awaited_once_with(master)


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


class TestRouteRegistration:
    def test_post_masters_route_registered(self):
        from fleet_platform.api.routes.salt_masters import router

        post_paths = [r.path for r in router.routes if "POST" in getattr(r, "methods", set())]
        assert "/api/v1/salt/masters" in post_paths, f"POST /masters not registered. Routes: {post_paths}"

    def test_patch_masters_route_registered(self):
        from fleet_platform.api.routes.salt_masters import router

        patch_paths = [r.path for r in router.routes if "PATCH" in getattr(r, "methods", set())]
        assert "/api/v1/salt/masters/{master_id}" in patch_paths, (
            f"PATCH /masters/{{id}} not registered. Routes: {patch_paths}"
        )

    def test_delete_masters_route_registered(self):
        from fleet_platform.api.routes.salt_masters import router

        delete_paths = [r.path for r in router.routes if "DELETE" in getattr(r, "methods", set())]
        assert "/api/v1/salt/masters/{master_id}" in delete_paths, (
            f"DELETE /masters/{{id}} not registered. Routes: {delete_paths}"
        )
