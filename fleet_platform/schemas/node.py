# fleet_platform/schemas/node.py
import uuid

from pydantic import BaseModel, field_validator

from fleet_platform.core.validators import validate_minion_id


class NodeRegisterRequest(BaseModel):
    minion_id: str
    hostname: str | None = None

    _validate_minion_id = field_validator("minion_id")(validate_minion_id)


class NodeRegisterResponse(BaseModel):
    node_id: uuid.UUID
    minion_id: str
    token: str
    message: str = "Token shown once. Store it in Salt pillar immediately."
