"""Pydantic schemas for the SaltMaster entity (#516, epic #523).

Response schema never exposes api_password_enc, ssh_key_enc, ssh_password_enc, or any secret.
Create/Update schemas accept api_password, ssh_key, ssh_password as write-only plaintext.
Provision lifecycle fields added in #556 (master-lifecycle epic).
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
    tls_verify: bool = False
    auto_accept: bool = True
    # SSH creds for provisioning (write-only plaintext — stored encrypted)
    ssh_host: str | None = Field(default=None, description="SSH host; defaults to address at provision time")
    ssh_user: str | None = Field(default=None, description="SSH username; defaults to global bootstrap user")
    ssh_key: str | None = Field(default=None, description="Plaintext SSH private key — stored encrypted")
    ssh_password: str | None = Field(default=None, description="Plaintext SSH password — stored encrypted")
    node_id: uuid.UUID | None = Field(default=None, description="Optional link to an existing node record")


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
    tls_verify: bool | None = None
    auto_accept: bool | None = None
    # SSH creds for provisioning (write-only plaintext — stored encrypted)
    ssh_host: str | None = None
    ssh_user: str | None = None
    ssh_key: str | None = Field(default=None, description="Plaintext SSH private key — stored encrypted")
    ssh_password: str | None = Field(default=None, description="Plaintext SSH password — stored encrypted")
    node_id: uuid.UUID | None = None


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
    tls_verify: bool
    auto_accept: bool
    status: str
    last_checked_at: datetime | None
    last_error: str | None
    # checks is a JSON list of per-check result objects (or None if never probed)
    checks: list[Any] | None
    # Provision lifecycle (#556)
    provision_status: str = "unprovisioned"
    os_family: str | None = None
    salt_version: str | None = None
    last_provisioned_at: datetime | None = None
    provision_error: str | None = None
    # SSH host/user readable (key/password are write-only — never returned)
    ssh_host: str | None = None
    ssh_user: str | None = None
    # ssh_key_enc / ssh_password_enc intentionally excluded — never returned to clients
    node_id: uuid.UUID | None = None
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

    @field_validator("provision_status", mode="before")
    @classmethod
    def coerce_provision_status(cls, v: Any) -> Any:
        """Coerce None to the default value — ORM objects return None before DB flush."""
        if v is None:
            return "unprovisioned"
        return v


class MasterProvisionRunResponse(BaseModel):
    id: uuid.UUID
    salt_master_id: uuid.UUID
    action: str
    status: str
    started_at: datetime
    finished_at: datetime | None
    ansible_stdout: str | None
    error: str | None

    model_config = {"from_attributes": True}
