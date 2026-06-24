import logging as _logging

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_log = _logging.getLogger(__name__)

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

    # Canonical env var is FERNET_KEY (matches CI and .env*.example). The legacy
    # name FERNET_SECRET_KEY is still accepted for backward compatibility so that
    # existing deployments keep decrypting secrets after the rename — otherwise
    # the explicit key would vanish on redeploy and every stored secret encrypted
    # under it would fail to decrypt. AliasChoices tries names in order, so when
    # both are set FERNET_KEY wins. The Python attribute stays fernet_secret_key.
    fernet_secret_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("FERNET_KEY", "FERNET_SECRET_KEY"),
    )

    # Static bearer token for the /metrics Prometheus scrape endpoint (#763).
    # If unset, only valid JWT bearer tokens are accepted.
    # Prometheus scrape config: authorization: { credentials: <METRICS_TOKEN> }
    metrics_token: str | None = None

    # Number of trusted reverse-proxy hops in front of the API (#759).
    # 0 = use request.client.host directly (no proxy; default).
    # N = skip the N rightmost X-Forwarded-For entries; the entry immediately
    # to their left is the real client IP used for rate-limiting.
    trusted_proxy_count: int = 0

    oidc_enabled: bool = False
    oidc_issuer_url: str = ""  # e.g. https://keycloak.example.com/realms/kri
    oidc_client_id: str = ""
    oidc_client_secret: str = ""
    oidc_role_prefix: str = "kri-"  # Keycloak role prefix: kri-admin → admin

    @model_validator(mode="after")
    def validate_production_secrets(self) -> "Settings":
        if self.jwt_secret in _INSECURE_SECRETS or len(self.jwt_secret) < 32:
            if self.environment == "production":
                raise ValueError(
                    "JWT_SECRET must be at least 32 characters and not a default/example value "
                    "when ENVIRONMENT=production. Generate with: openssl rand -hex 32"
                )
            else:
                _log.warning(
                    "JWT_SECRET is insecure (%r) — all encrypted secrets use a known key. "
                    "Set JWT_SECRET in .env before handling real data.",
                    self.jwt_secret[:8] + "..." if len(self.jwt_secret) > 8 else self.jwt_secret,
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
