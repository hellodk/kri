import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class SBOMScanResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    node_id: uuid.UUID
    syft_version: str | None
    format: str
    scanned_at: datetime
    component_count: int | None


class SBOMComponentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    scan_id: uuid.UUID
    node_id: uuid.UUID
    name: str
    version: str | None
    purl: str | None
    component_type: str | None
    licenses: list[str]
    cpes: list[str]


class SBOMSearchResult(BaseModel):
    name: str
    version: str | None
    purl: str | None
    component_type: str | None
    hostname: str
    node_id: uuid.UUID
    scan_id: uuid.UUID
    scanned_at: datetime
