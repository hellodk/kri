# fleet_platform/schemas/node.py
import uuid

from pydantic import BaseModel


class NodeRegisterRequest(BaseModel):
    minion_id: str
    hostname: str | None = None


class NodeRegisterResponse(BaseModel):
    node_id: uuid.UUID
    minion_id: str
    token: str
    message: str = "Token shown once. Store it in Salt pillar immediately."
