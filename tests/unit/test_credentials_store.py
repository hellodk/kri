"""Unit tests for credentials store — TDD first pass (#389)."""

import pathlib

import pytest

from fleet_platform.schemas.credential import (
    CredentialCreate,
    CredentialResponse,
    CredentialUpdate,
)

# ---------------------------------------------------------------------------
# Schema shape tests
# ---------------------------------------------------------------------------


class TestCredentialResponse:
    def test_response_has_no_secret_field(self):
        fields = CredentialResponse.model_fields
        assert "secret" not in fields, "CredentialResponse must NOT expose 'secret'"
        assert "secret_enc" not in fields, "CredentialResponse must NOT expose 'secret_enc'"

    def test_response_has_required_fields(self):
        fields = CredentialResponse.model_fields
        for f in ("id", "name", "kind", "created_at"):
            assert f in fields, f"CredentialResponse is missing field: {f!r}"

    def test_response_optional_fields(self):
        fields = CredentialResponse.model_fields
        for f in ("username", "description", "last_used_at"):
            assert f in fields, f"CredentialResponse is missing optional field: {f!r}"


class TestCredentialCreate:
    def test_create_requires_name_kind_secret(self):
        with pytest.raises(Exception):
            CredentialCreate()  # all required fields missing

    def test_create_valid(self):
        obj = CredentialCreate(name="github-token", kind="token", secret="ghp_xxx")
        assert obj.name == "github-token"
        assert obj.kind == "token"
        assert obj.secret == "ghp_xxx"

    def test_create_optional_fields(self):
        obj = CredentialCreate(
            name="svc",
            kind="username_password",
            secret="pass",
            username="svcuser",
            description="desc",
        )
        assert obj.username == "svcuser"
        assert obj.description == "desc"


class TestCredentialUpdate:
    def test_update_all_optional(self):
        # Should succeed with no fields
        obj = CredentialUpdate()
        assert obj is not None

    def test_update_partial(self):
        obj = CredentialUpdate(description="new desc")
        assert obj.description == "new desc"


# ---------------------------------------------------------------------------
# Router prefix + main.py inclusion
# ---------------------------------------------------------------------------


class TestCredentialsRouterRegistration:
    def test_router_prefix(self):
        from fleet_platform.api.routes import credentials as creds_mod

        assert (
            creds_mod.router.prefix == "/api/v1/credentials"
        ), f"Expected prefix /api/v1/credentials, got {creds_mod.router.prefix!r}"

    def test_main_includes_credentials_router(self):
        main_src = pathlib.Path("fleet_platform/api/main.py").read_text()
        assert "credentials" in main_src, "api/main.py does not reference credentials router"


# ---------------------------------------------------------------------------
# Migration file assertion
# ---------------------------------------------------------------------------


class TestMigration038:
    def test_migration_038_exists(self):
        migration_path = pathlib.Path("fleet_platform/db/migrations/versions/038_credentials.py")
        assert migration_path.exists(), f"Migration file not found: {migration_path}"

    def test_migration_038_revision(self):
        migration_path = pathlib.Path("fleet_platform/db/migrations/versions/038_credentials.py")
        src = migration_path.read_text()
        assert "revision = '038'" in src, "Migration must declare revision = '038'"
        assert "down_revision = '037'" in src, "Migration must declare down_revision = '037'"
