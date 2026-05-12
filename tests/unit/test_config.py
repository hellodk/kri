from fleet_platform.core.config import Settings


def test_defaults_are_sane():
    s = Settings()
    assert s.jwt_algorithm == "HS256"
    assert s.jwt_access_token_expire_minutes == 15
    assert s.jwt_refresh_token_expire_days == 7
    assert s.environment == "development"
    assert s.is_development is True


def test_is_development_false_in_production(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    s = Settings()
    assert s.is_development is False


def test_database_url_is_set():
    s = Settings()
    assert "postgresql" in s.database_url
    assert "fleet_platform" in s.database_url
