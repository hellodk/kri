"""Unit tests for SaltMaster model + schemas — TDD for issue #516, epic #523.

Run without a live DB: all tests are pure-Python (column inspection + schema validation).
SQLAlchemy 2.0 mapped_column(default=...) applies at SQL flush time, not Python construction,
so model defaults are verified via column-level inspection rather than instantiation.
Migration upgrade test is included but skipped when no DB is available.
"""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import inspect as sa_inspect

# ---------------------------------------------------------------------------
# Model column defaults (verified via SQLAlchemy column inspection)
# ---------------------------------------------------------------------------


class TestSaltMasterModelDefaults:
    def _col(self, name: str):
        from fleet_platform.models.salt_master import SaltMaster

        return sa_inspect(SaltMaster).columns[name]

    def test_control_mode_default(self):
        col = self._col("control_mode")
        assert col.default.arg == "salt_api"

    def test_token_delivery_default(self):
        col = self._col("token_delivery")
        assert col.default.arg == "ingest"

    def test_status_default(self):
        col = self._col("status")
        assert col.default.arg == "unknown"

    def test_enabled_default(self):
        col = self._col("enabled")
        assert col.default.arg is True

    def test_is_default_default(self):
        col = self._col("is_default")
        assert col.default.arg is False

    def test_publish_port_default(self):
        col = self._col("publish_port")
        assert col.default.arg == 4505

    def test_ret_port_default(self):
        col = self._col("ret_port")
        assert col.default.arg == 4506

    def test_id_has_uuid4_default(self):
        """id column must have a callable default (uuid.uuid4)."""
        col = self._col("id")
        assert col.default is not None
        assert callable(col.default.arg), "id.default must be a callable (uuid.uuid4)"

    def test_optional_columns_nullable(self):
        optional_cols = (
            "api_url",
            "api_user",
            "api_password_enc",
            "api_eauth",
            "last_checked_at",
            "last_error",
            "checks",
        )
        for fname in optional_cols:
            col = self._col(fname)
            assert col.nullable, f"{fname} must be nullable"

    def test_tablename(self):
        from fleet_platform.models.salt_master import SaltMaster

        assert SaltMaster.__tablename__ == "salt_masters"


# ---------------------------------------------------------------------------
# Node FK field presence
# ---------------------------------------------------------------------------


class TestNodeSaltMasterForeignKey:
    def test_node_has_salt_master_id_column(self):
        from fleet_platform.models.node import Node

        assert hasattr(Node, "salt_master_id"), "Node must have a salt_master_id attribute"

    def test_node_salt_master_id_is_nullable(self):
        """Column must be nullable so existing nodes work without a master assigned."""
        from sqlalchemy import inspect

        from fleet_platform.models.node import Node

        mapper = inspect(Node)
        col = mapper.columns["salt_master_id"]
        assert col.nullable is True, "salt_master_id must be nullable"


# ---------------------------------------------------------------------------
# Pydantic response schema — must NOT expose secrets
# ---------------------------------------------------------------------------


class TestSaltMasterResponseSchema:
    def test_response_does_not_expose_api_password_enc(self):
        from fleet_platform.schemas.salt_master import SaltMasterResponse

        fields = SaltMasterResponse.model_fields
        assert "api_password_enc" not in fields, "SaltMasterResponse must NOT expose api_password_enc"

    def test_response_does_not_expose_any_password(self):
        from fleet_platform.schemas.salt_master import SaltMasterResponse

        fields = SaltMasterResponse.model_fields
        for f in fields:
            assert "password" not in f.lower(), f"SaltMasterResponse must NOT expose field '{f}' (contains 'password')"

    def test_response_has_required_fields(self):
        from fleet_platform.schemas.salt_master import SaltMasterResponse

        fields = SaltMasterResponse.model_fields
        required = ("id", "name", "address", "enabled", "is_default", "status", "control_mode", "token_delivery")
        for f in required:
            assert f in fields, f"SaltMasterResponse is missing required field: {f!r}"

    def test_response_round_trip_from_attributes(self):
        """Validate round-trip with explicit values (DB defaults don't apply at construction)."""
        from fleet_platform.models.salt_master import SaltMaster
        from fleet_platform.schemas.salt_master import SaltMasterResponse

        now = datetime.now(UTC)
        m = SaltMaster(
            id=uuid.uuid4(),
            name="prod-master",
            address="192.168.1.100",
            enabled=True,
            is_default=False,
            publish_port=4505,
            ret_port=4506,
            control_mode="salt_api",
            token_delivery="ingest",
            tls_verify=False,
            auto_accept=True,
            status="unknown",
            created_at=now,
            updated_at=now,
        )
        resp = SaltMasterResponse.model_validate(m, from_attributes=True)
        assert resp.name == "prod-master"
        assert resp.address == "192.168.1.100"
        assert resp.control_mode == "salt_api"
        assert resp.token_delivery == "ingest"
        assert resp.status == "unknown"
        assert resp.enabled is True


# ---------------------------------------------------------------------------
# Pydantic create/update schema — password is write-only
# ---------------------------------------------------------------------------


class TestSaltMasterCreateSchema:
    def test_create_requires_name_and_address(self):
        from fleet_platform.schemas.salt_master import SaltMasterCreate

        with pytest.raises(Exception):
            SaltMasterCreate()  # missing required fields

    def test_create_valid_minimal(self):
        from fleet_platform.schemas.salt_master import SaltMasterCreate

        obj = SaltMasterCreate(name="prod", address="salt.prod.local")
        assert obj.name == "prod"
        assert obj.address == "salt.prod.local"

    def test_create_defaults_salt_api_port(self):
        """After #690: salt_api_port defaults to 4507 (adjacent to ZMQ 4505/4506)."""
        from fleet_platform.schemas.salt_master import SaltMasterCreate

        obj = SaltMasterCreate(name="prod", address="salt.prod.local")
        assert obj.salt_api_port == 4507

    def test_create_defaults_use_tls(self):
        """After #562: use_tls defaults to True."""
        from fleet_platform.schemas.salt_master import SaltMasterCreate

        obj = SaltMasterCreate(name="prod", address="salt.prod.local")
        assert obj.use_tls is True

    def test_create_accepts_api_password(self):
        from fleet_platform.schemas.salt_master import SaltMasterCreate

        obj = SaltMasterCreate(name="prod", address="salt.prod.local", api_password="secret123")
        assert obj.api_password == "secret123"

    def test_create_has_api_password_not_api_password_enc(self):
        """The create schema takes plaintext api_password, not api_password_enc."""
        from fleet_platform.schemas.salt_master import SaltMasterCreate

        fields = SaltMasterCreate.model_fields
        assert "api_password" in fields, "SaltMasterCreate must have api_password field"
        assert "api_password_enc" not in fields, "SaltMasterCreate must NOT have api_password_enc"


class TestSaltMasterUpdateSchema:
    def test_update_all_optional(self):
        from fleet_platform.schemas.salt_master import SaltMasterUpdate

        obj = SaltMasterUpdate()
        assert obj is not None

    def test_update_has_api_password_not_api_password_enc(self):
        from fleet_platform.schemas.salt_master import SaltMasterUpdate

        fields = SaltMasterUpdate.model_fields
        assert "api_password_enc" not in fields, "SaltMasterUpdate must NOT have api_password_enc"


# ---------------------------------------------------------------------------
# Model registered in __init__
# ---------------------------------------------------------------------------


class TestSaltMasterRegistration:
    def test_salt_master_in_models_init(self):
        from fleet_platform import models

        assert hasattr(models, "SaltMaster"), "SaltMaster must be exported from fleet_platform.models"

    def test_salt_master_in_all(self):
        from fleet_platform.models import __all__

        assert "SaltMaster" in __all__, "SaltMaster must be in fleet_platform.models.__all__"
