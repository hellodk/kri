from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_INSECURE_SECRETS = {
    "insecure-dev-secret",
    "change-me-generate-with-openssl-rand-hex-32",
    "",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://fleet:fleet@localhost:5432/fleet_platform"
    test_database_url: str = "postgresql+psycopg://fleet:fleet@localhost:5432/fleet_test"
    redis_url: str = "redis://:redispass@localhost:6379/0"

    jwt_secret: str = "insecure-dev-secret"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 15
    jwt_refresh_token_expire_days: int = 7

    frontend_origin: str = "http://localhost:5173"
    environment: str = "development"

    fernet_secret_key: str | None = (
        None  # separate key for encrypting platform secrets; if unset, derived from jwt_secret
    )

    oidc_enabled: bool = False
    oidc_issuer_url: str = ""  # e.g. https://keycloak.example.com/realms/kri
    oidc_client_id: str = ""
    oidc_client_secret: str = ""
    oidc_role_prefix: str = "kri-"  # Keycloak role prefix: kri-admin → admin

    @model_validator(mode="after")
    def validate_production_secrets(self) -> "Settings":
        if self.environment == "production":
            if self.jwt_secret in _INSECURE_SECRETS or len(self.jwt_secret) < 32:
                raise ValueError(
                    "JWT_SECRET must be at least 32 characters and not a default/example value "
                    "when ENVIRONMENT=production. Generate with: openssl rand -hex 32"
                )
        return self

    @property
    def is_development(self) -> bool:
        return self.environment == "development"


settings = Settings()


def _read_version() -> str:
    from pathlib import Path

    for candidate in [
        Path(__file__).parent.parent.parent / "VERSION",  # repo root
        Path("/app/VERSION"),  # Docker container
    ]:
        if candidate.exists():
            return candidate.read_text().strip()
    return "0.0.0"


VERSION = _read_version()
