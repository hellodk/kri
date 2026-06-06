import pytest


def test_defaults_are_sane():
    import fleet_platform.core.config

    s = fleet_platform.core.config.Settings()
    assert s.jwt_algorithm == "HS256"
    assert s.jwt_access_token_expire_minutes == 15
    assert s.jwt_refresh_token_expire_days == 7
    assert s.environment == "development"
    assert s.is_development is True


def test_is_development_false_in_production(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("JWT_SECRET", "a" * 32)
    import fleet_platform.core.config

    s = fleet_platform.core.config.Settings()
    assert s.is_development is False


def test_database_url_is_set():
    import fleet_platform.core.config

    s = fleet_platform.core.config.Settings()
    assert "postgresql" in s.database_url
    assert "fleet_" in s.database_url  # can be fleet_platform or fleet_demo depending on .env


def test_insecure_jwt_secret_rejected_in_production(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("JWT_SECRET", "insecure-dev-secret")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://x:x@localhost/x")
    from fleet_platform.core.config import Settings

    with pytest.raises((ValueError, Exception)):
        _ = Settings()


def test_short_jwt_secret_rejected_in_production(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("JWT_SECRET", "tooshort")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://x:x@localhost/x")
    from fleet_platform.core.config import Settings

    with pytest.raises((ValueError, Exception)):
        _ = Settings()


def test_good_jwt_secret_accepted_in_production(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("JWT_SECRET", "a" * 32)
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://x:x@localhost/x")
    from fleet_platform.core.config import Settings

    s = Settings()
    assert s.environment == "production"
