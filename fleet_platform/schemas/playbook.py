# fleet_platform/schemas/playbook.py
import uuid
from datetime import datetime
from pydantic import BaseModel


class PlaybookEntryResponse(BaseModel):
    filename: str
    name: str
    description: str | None
    entry_type: str
    default_vars: dict


class PlaybookRunRequest(BaseModel):
    playbook: str
    target_type: str
    target_id: str
    extravars: dict = {}
    ssh_username: str | None = None   # overrides platform setting ssh_bootstrap_username
    ssh_password: str | None = None   # overrides platform setting ssh_bootstrap_password


class PlaybookRunResponse(BaseModel):
    job_id: uuid.UUID
    playbook: str
    target_label: str
    status: str
    message: str


class AnsibleJobResponse(BaseModel):
    id: uuid.UUID
    playbook: str
    target_type: str
    target_label: str
    extravars: dict
    status: str
    triggered_by: str
    started_at: datetime | None
    completed_at: datetime | None
    stdout: str | None
    rc: int | None
    created_at: datetime
