import uuid
from datetime import datetime

from pydantic import BaseModel, model_validator


class GroupCreate(BaseModel):
    name: str
    description: str | None = None
    type: str  # "static" or "dynamic"
    predicate: dict | None = None

    @model_validator(mode="after")
    def predicate_required_for_dynamic(self) -> "GroupCreate":
        if self.type == "dynamic" and not self.predicate:
            raise ValueError("predicate is required for dynamic groups")
        return self


class GroupUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    predicate: dict | None = None


class GroupResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    type: str
    predicate: dict | None
    member_count: int = 0
    created_at: datetime

    model_config = {"from_attributes": True}


class GroupMemberAdd(BaseModel):
    node_id: uuid.UUID
