import uuid
from datetime import datetime

from pydantic import BaseModel


class ProvisioningProfileResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    name: str
    filename: str
    bundle_id: str | None
    team_name: str | None
    expiry_date: datetime | None
    profile_type: str
    description: str | None
    uploaded_by: str
    created_at: datetime


class ProvisioningProfileList(BaseModel):
    items: list[ProvisioningProfileResponse]
    total: int
