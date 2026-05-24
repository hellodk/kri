# fleet_platform/schemas/execution.py
import uuid
from datetime import datetime

from pydantic import BaseModel


class ExecutionJobResponse(BaseModel):
    id: uuid.UUID
    salt_jid: str | None = None
    type: str
    target_type: str
    target_id: uuid.UUID | None = None
    triggered_by: str
    status: str
    started_at: datetime | None = None
    completed_at: datetime | None = None

    model_config = {"from_attributes": True}


class ExecutionResultResponse(BaseModel):
    id: uuid.UUID
    job_id: uuid.UUID
    node_id: uuid.UUID
    status: str
    exit_code: int | None = None
    stdout: str | None = None
    stderr: str | None = None
    completed_at: datetime

    model_config = {"from_attributes": True}
