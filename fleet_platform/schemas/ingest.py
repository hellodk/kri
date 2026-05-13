# fleet_platform/schemas/ingest.py
from pydantic import BaseModel


class GrainIngestPayload(BaseModel):
    minion_id: str
    grains: dict


class ExecutionIngestPayload(BaseModel):
    minion_id: str
    jid: str
    return_data: dict
    fun: str
    retcode: int = 0
    success: bool = True


class SBOMIngestAck(BaseModel):
    status: str = "queued"
    node_id: str
