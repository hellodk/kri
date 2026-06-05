"""Pydantic schemas for macOS configuration profile management."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class MobileconfigProfileCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=256)
    description: str | None = None
    payload_xml: str = Field(..., min_length=1)  # raw .mobileconfig XML


class MobileconfigProfileResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    profile_uuid: str | None  # extracted from XML
    version: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ProfileDeployRequest(BaseModel):
    node_ids: list[uuid.UUID]
    action: Literal["install", "remove"] = "install"


class ProfileComplianceResponse(BaseModel):
    profile_id: uuid.UUID
    node_id: uuid.UUID
    node_hostname: str | None
    status: str  # "installed" | "not_installed" | "pending" | "failed" | "unknown"
    last_deployed_at: datetime | None
