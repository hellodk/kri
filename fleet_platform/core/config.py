from pydantic_settings import BaseSettings, SettingsConfigDict


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

    @property
    def is_development(self) -> bool:
        return self.environment == "development"


settings = Settings()

VERSION = "0.1.0"
