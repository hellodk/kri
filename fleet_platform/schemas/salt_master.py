"""Pydantic schemas for the SaltMaster entity (#516, epic #523).

Response schema never exposes api_password_enc or any secret.
Create/Update schemas accept api_password as write-only plaintext.
"""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


class SaltMasterCreate(BaseModel):
    name: str = Field(..., description="Unique display name for this salt master")
    address: str = Field(..., description="Hostname or IP address of the salt master")
    enabled: bool = True
    is_default: bool = False
    publish_port: int = Field(default=4505, ge=1, le=65535)
    ret_port: int = Field(default=4506, ge=1, le=65535)
    control_mode: str = Field(default="salt_api", description="'salt_api' or 'cli'")
    api_url: str | None = None
    api_user: str | None = None
    api_password: str | None = Field(default=None, description="Plaintext password — stored encrypted")
    api_eauth: str | None = None
    token_delivery: str = Field(default="ingest", description="'ingest' or 'direct'")


class SaltMasterUpdate(BaseModel):
    name: str | None = None
    address: str | None = None
    enabled: bool | None = None
    is_default: bool | None = None
    publish_port: int | None = Field(default=None, ge=1, le=65535)
    ret_port: int | None = Field(default=None, ge=1, le=65535)
    control_mode: str | None = None
    api_url: str | None = None
    api_user: str | None = None
    api_password: str | None = Field(default=None, description="Plaintext password — stored encrypted")
    api_eauth: str | None = None
    token_delivery: str | None = None


class SaltMasterResponse(BaseModel):
    id: uuid.UUID
    name: str
    enabled: bool
    is_default: bool
    address: str
    publish_port: int
    ret_port: int
    control_mode: str
    api_url: str | None
    api_user: str | None
    # api_password_enc intentionally excluded — never returned to clients
    api_eauth: str | None
    token_delivery: str
    status: str
    last_checked_at: datetime | None
    last_error: str | None
    # checks is a JSON list of per-check result objects (or None if never probed)
    checks: list[Any] | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @field_validator("checks", mode="before")
    @classmethod
    def coerce_checks(cls, v: Any) -> Any:
        """Accept either None, a list, or a dict (legacy) for the checks field."""
        if v is None:
            return v
        if isinstance(v, list):
            return v
        if isinstance(v, dict):
            return list(v.values())
        return v
