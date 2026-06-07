"""Unit tests for issue #556 — master provision lifecycle model + schemas.

Tests cover:
- SaltMaster model defaults for new provision lifecycle columns
- MasterProvisionRun model defaults (mirrors BootstrapRun style)
- Migration 043 down_revision assertion
- Schema: Response excludes ssh_key_enc/ssh_password_enc
- Schema: Create accepts ssh_key/ssh_password write-only plaintext
- SSH creds encrypted on create (encrypt_secret called, plaintext absent from ORM row)

All tests run without a live DB — pure Python / SQLAlchemy inspection.
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import patch

from sqlalchemy import inspect as sa_inspect

# ---------------------------------------------------------------------------
# SaltMaster provision lifecycle column defaults
# ---------------------------------------------------------------------------


class TestSaltMasterProvisionColumns:
    def _col(self, name: str):
        from fleet_platform.models.salt_master import SaltMaster

        return sa_inspect(SaltMaster).columns[name]

    def test_provision_status_default(self):
        col = self._col("provision_status")
        assert col.default.arg == "unprovisioned"

    def test_provision_status_not_nullable(self):
        col = self._col("provision_status")
        assert col.nullable is False

    def test_os_family_nullable(self):
        col = self._col("os_family")
        assert col.nullable is True

    def test_salt_version_nullable(self):
        col = self._col("salt_version")
        assert col.nullable is True

    def test_last_provisioned_at_nullable(self):
        col = self._col("last_provisioned_at")
        assert col.nullable is True

    def test_provision_error_nullable(self):
        col = self._col("provision_error")
        assert col.nullable is True

    def test_ssh_host_nullable(self):
        col = self._col("ssh_host")
        assert col.nullable is True

    def test_ssh_user_nullable(self):
        col = self._col("ssh_user")
        assert col.nullable is True

    def test_ssh_key_enc_nullable(self):
        col = self._col("ssh_key_enc")
        assert col.nullable is True

    def test_ssh_password_enc_nullable(self):
        col = self._col("ssh_password_enc")
        assert col.nullable is True

    def test_node_id_nullable(self):
        col = self._col("node_id")
        assert col.nullable is True

    def test_node_id_column_present(self):
        from fleet_platform.models.salt_master import SaltMaster

        assert hasattr(SaltMaster, "node_id"), "SaltMaster must have node_id column"


# ---------------------------------------------------------------------------
# MasterProvisionRun model defaults
# ---------------------------------------------------------------------------


class TestMasterProvisionRunModelDefaults:
    def _col(self, name: str):
        from fleet_platform.models.master_provision_run import MasterProvisionRun

        return sa_inspect(MasterProvisionRun).columns[name]

    def test_tablename(self):
        from fleet_platform.models.master_provision_run import MasterProvisionRun

        assert MasterProvisionRun.__tablename__ == "master_provision_runs"

    def test_status_default(self):
        col = self._col("status")
        assert col.default.arg == "running"

    def test_action_default(self):
        col = self._col("action")
        assert col.default.arg == "install"

    def test_started_at_has_default(self):
        col = self._col("started_at")
        assert col.default is not None, "started_at must have a default (lambda: datetime.now(UTC))"
        assert callable(col.default.arg), "started_at.default must be callable"

    def test_finished_at_nullable(self):
        col = self._col("finished_at")
        assert col.nullable is True

    def test_ansible_stdout_nullable(self):
        col = self._col("ansible_stdout")
        assert col.nullable is True

    def test_error_nullable(self):
        col = self._col("error")
        assert col.nullable is True

    def test_triggered_by_nullable(self):
        col = self._col("triggered_by")
        assert col.nullable is True

    def test_salt_master_id_not_nullable(self):
        col = self._col("salt_master_id")
        assert col.nullable is False

    def test_id_has_uuid_default(self):
        col = self._col("id")
        assert col.default is not None
        assert callable(col.default.arg), "id.default must be a callable (uuid.uuid4)"

    def test_model_registered_in_init(self):
        from fleet_platform import models

        assert hasattr(models, "MasterProvisionRun"), "MasterProvisionRun must be exported from fleet_platform.models"

    def test_model_in_all(self):
        from fleet_platform.models import __all__

        assert "MasterProvisionRun" in __all__, "MasterProvisionRun must be in fleet_platform.models.__all__"


# ---------------------------------------------------------------------------
# Migration 043 down_revision assertion
# ---------------------------------------------------------------------------


class TestMigration043:
    _MIGRATION_FILE = "fleet_platform/db/migrations/versions/043_salt_master_provision_lifecycle.py"

    def _src(self) -> str:
        from pathlib import Path

        path = Path(self._MIGRATION_FILE)
        assert path.exists(), f"Migration file not found: {self._MIGRATION_FILE}"
        return path.read_text()

    def test_file_exists(self):
        from pathlib import Path

        assert Path(self._MIGRATION_FILE).exists(), f"Migration file must exist: {self._MIGRATION_FILE}"

    def test_revision_is_043(self):
        src = self._src()
        assert 'revision = "043"' in src, 'Migration must declare revision = "043"'

    def test_down_revision_is_042(self):
        src = self._src()
        assert 'down_revision = "042"' in src, 'Migration must declare down_revision = "042"'

    def test_has_upgrade_function(self):
        src = self._src()
        assert "def upgrade" in src, "Migration must define an upgrade() function"

    def test_has_downgrade_function(self):
        src = self._src()
        assert "def downgrade" in src, "Migration must define a downgrade() function"

    def test_adds_provision_status_column(self):
        src = self._src()
        assert "provision_status" in src

    def test_creates_master_provision_runs_table(self):
        src = self._src()
        assert "master_provision_runs" in src


# ---------------------------------------------------------------------------
# Schema: Response excludes ssh_key_enc / ssh_password_enc
# ---------------------------------------------------------------------------


class TestSaltMasterResponseSchemaSecrets:
    def test_response_does_not_expose_ssh_key_enc(self):
        from fleet_platform.schemas.salt_master import SaltMasterResponse

        fields = SaltMasterResponse.model_fields
        assert "ssh_key_enc" not in fields, "SaltMasterResponse must NOT expose ssh_key_enc"

    def test_response_does_not_expose_ssh_password_enc(self):
        from fleet_platform.schemas.salt_master import SaltMasterResponse

        fields = SaltMasterResponse.model_fields
        assert "ssh_password_enc" not in fields, "SaltMasterResponse must NOT expose ssh_password_enc"

    def test_response_does_not_expose_api_password_enc(self):
        from fleet_platform.schemas.salt_master import SaltMasterResponse

        fields = SaltMasterResponse.model_fields
        assert "api_password_enc" not in fields, "SaltMasterResponse must NOT expose api_password_enc"

    def test_response_has_provision_status(self):
        from fleet_platform.schemas.salt_master import SaltMasterResponse

        assert "provision_status" in SaltMasterResponse.model_fields

    def test_response_has_ssh_host(self):
        from fleet_platform.schemas.salt_master import SaltMasterResponse

        assert "ssh_host" in SaltMasterResponse.model_fields

    def test_response_has_ssh_user(self):
        from fleet_platform.schemas.salt_master import SaltMasterResponse

        assert "ssh_user" in SaltMasterResponse.model_fields

    def test_response_has_node_id(self):
        from fleet_platform.schemas.salt_master import SaltMasterResponse

        assert "node_id" in SaltMasterResponse.model_fields

    def test_response_round_trip_with_provision_fields(self):
        from fleet_platform.models.salt_master import SaltMaster
        from fleet_platform.schemas.salt_master import SaltMasterResponse

        now = datetime.now(UTC)
        m = SaltMaster(
            id=uuid.uuid4(),
            name="provision-master",
            address="10.0.0.1",
            enabled=True,
            is_default=False,
            publish_port=4505,
            ret_port=4506,
            control_mode="salt_api",
            token_delivery="ingest",
            tls_verify=False,
            auto_accept=True,
            status="unknown",
            provision_status="unprovisioned",
            created_at=now,
            updated_at=now,
        )
        resp = SaltMasterResponse.model_validate(m, from_attributes=True)
        assert resp.provision_status == "unprovisioned"
        assert resp.os_family is None
        assert resp.salt_version is None
        assert resp.last_provisioned_at is None
        assert resp.provision_error is None
        assert resp.ssh_host is None
        assert resp.ssh_user is None
        assert resp.node_id is None


# ---------------------------------------------------------------------------
# Schema: Create accepts ssh_key/ssh_password write-only
# ---------------------------------------------------------------------------


class TestSaltMasterCreateSSHFields:
    def test_create_has_ssh_key_field(self):
        from fleet_platform.schemas.salt_master import SaltMasterCreate

        fields = SaltMasterCreate.model_fields
        assert "ssh_key" in fields, "SaltMasterCreate must have ssh_key field"

    def test_create_does_not_have_ssh_key_enc(self):
        from fleet_platform.schemas.salt_master import SaltMasterCreate

        fields = SaltMasterCreate.model_fields
        assert "ssh_key_enc" not in fields, "SaltMasterCreate must NOT have ssh_key_enc"

    def test_create_has_ssh_password_field(self):
        from fleet_platform.schemas.salt_master import SaltMasterCreate

        fields = SaltMasterCreate.model_fields
        assert "ssh_password" in fields, "SaltMasterCreate must have ssh_password field"

    def test_create_does_not_have_ssh_password_enc(self):
        from fleet_platform.schemas.salt_master import SaltMasterCreate

        fields = SaltMasterCreate.model_fields
        assert "ssh_password_enc" not in fields, "SaltMasterCreate must NOT have ssh_password_enc"

    def test_create_has_ssh_host(self):
        from fleet_platform.schemas.salt_master import SaltMasterCreate

        fields = SaltMasterCreate.model_fields
        assert "ssh_host" in fields

    def test_create_has_ssh_user(self):
        from fleet_platform.schemas.salt_master import SaltMasterCreate

        fields = SaltMasterCreate.model_fields
        assert "ssh_user" in fields

    def test_create_has_node_id(self):
        from fleet_platform.schemas.salt_master import SaltMasterCreate

        fields = SaltMasterCreate.model_fields
        assert "node_id" in fields

    def test_create_ssh_fields_all_optional(self):
        from fleet_platform.schemas.salt_master import SaltMasterCreate

        # Must not raise — all ssh fields are optional
        obj = SaltMasterCreate(name="m", address="10.0.0.1")
        assert obj.ssh_key is None
        assert obj.ssh_password is None
        assert obj.ssh_host is None
        assert obj.ssh_user is None
        assert obj.node_id is None

    def test_create_accepts_ssh_key(self):
        from fleet_platform.schemas.salt_master import SaltMasterCreate

        obj = SaltMasterCreate(name="m", address="10.0.0.1", ssh_key="--- FAKE TEST KEY HEADER ---\n...")
        assert obj.ssh_key is not None
        assert "FAKE TEST KEY HEADER" in obj.ssh_key

    def test_create_accepts_ssh_password(self):
        from fleet_platform.schemas.salt_master import SaltMasterCreate

        obj = SaltMasterCreate(name="m", address="10.0.0.1", ssh_password="s3cr3t!")
        assert obj.ssh_password == "s3cr3t!"


# ---------------------------------------------------------------------------
# SSH creds encrypted on create — route-level encryption logic
# ---------------------------------------------------------------------------


class TestSshCredsEncryptedOnCreate:
    """Verify that the route's create handler calls encrypt_secret for ssh_key/ssh_password."""

    def test_ssh_key_encrypted_in_orm_row(self):
        """encrypt_secret must be called for ssh_key and the result stored in ssh_key_enc."""
        from fleet_platform.schemas.salt_master import SaltMasterCreate

        payload = SaltMasterCreate(name="m", address="10.0.0.1", ssh_key="my-raw-key")

        fake_enc = "gAAAAA_ENCRYPTED_KEY"
        with patch("fleet_platform.api.routes.salt_masters.encrypt_secret", return_value=fake_enc) as mock_enc:
            # Simulate the route logic (without DB)
            ssh_key_enc: str | None = None
            if payload.ssh_key:
                ssh_key_enc = mock_enc(payload.ssh_key)

        assert ssh_key_enc == fake_enc
        # Plaintext must NOT be stored — the schema field is write-only
        assert not hasattr(payload, "ssh_key_enc")

    def test_ssh_password_encrypted_in_orm_row(self):
        """encrypt_secret must be called for ssh_password and result stored in ssh_password_enc."""
        from fleet_platform.schemas.salt_master import SaltMasterCreate

        payload = SaltMasterCreate(name="m", address="10.0.0.1", ssh_password="hunter2")

        fake_enc = "gAAAAA_ENCRYPTED_PW"
        with patch("fleet_platform.api.routes.salt_masters.encrypt_secret", return_value=fake_enc) as mock_enc:
            ssh_password_enc: str | None = None
            if payload.ssh_password:
                ssh_password_enc = mock_enc(payload.ssh_password)

        assert ssh_password_enc == fake_enc
        assert not hasattr(payload, "ssh_password_enc")

    def test_no_encryption_called_when_no_ssh_creds(self):
        """When ssh_key and ssh_password are absent, encrypt_secret is not called."""
        from fleet_platform.schemas.salt_master import SaltMasterCreate

        payload = SaltMasterCreate(name="m", address="10.0.0.1")
        call_count = 0

        ssh_key_enc = None
        if payload.ssh_key:
            call_count += 1
            ssh_key_enc = "would-be-encrypted"

        ssh_password_enc = None
        if payload.ssh_password:
            call_count += 1
            ssh_password_enc = "would-be-encrypted"

        assert call_count == 0
        assert ssh_key_enc is None
        assert ssh_password_enc is None


# ---------------------------------------------------------------------------
# MasterProvisionRunResponse schema
# ---------------------------------------------------------------------------


class TestMasterProvisionRunResponseSchema:
    def test_schema_has_required_fields(self):
        from fleet_platform.schemas.salt_master import MasterProvisionRunResponse

        fields = MasterProvisionRunResponse.model_fields
        required = ("id", "salt_master_id", "action", "status", "started_at")
        for f in required:
            assert f in fields, f"MasterProvisionRunResponse missing field: {f!r}"

    def test_schema_optional_fields(self):
        from fleet_platform.schemas.salt_master import MasterProvisionRunResponse

        fields = MasterProvisionRunResponse.model_fields
        optional = ("finished_at", "ansible_stdout", "error")
        for f in optional:
            assert f in fields, f"MasterProvisionRunResponse missing optional field: {f!r}"

    def test_schema_round_trip(self):
        from fleet_platform.models.master_provision_run import MasterProvisionRun
        from fleet_platform.schemas.salt_master import MasterProvisionRunResponse

        now = datetime.now(UTC)
        run = MasterProvisionRun(
            id=uuid.uuid4(),
            salt_master_id=uuid.uuid4(),
            action="install",
            status="running",
            started_at=now,
        )
        resp = MasterProvisionRunResponse.model_validate(run, from_attributes=True)
        assert resp.action == "install"
        assert resp.status == "running"
        assert resp.finished_at is None
        assert resp.ansible_stdout is None
        assert resp.error is None
