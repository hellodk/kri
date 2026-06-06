"""Pydantic schemas for the credentials store (#389)."""

import uuid
from datetime import datetime

from pydantic import BaseModel


class CredentialCreate(BaseModel):
    name: str
    kind: str  # token | ssh_key | username_password
    secret: str
    username: str | None = None
    description: str | None = None


class CredentialUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    username: str | None = None
    secret: str | None = None


class CredentialResponse(BaseModel):
    id: uuid.UUID
    name: str
    kind: str
    username: str | None = None
    description: str | None = None
    created_at: datetime
    last_used_at: datetime | None = None

    model_config = {"from_attributes": True}
