# fleet_platform/schemas/ansible.py
import uuid
from pydantic import BaseModel


class BootstrapRequest(BaseModel):
    minion_id: str
    target_ip: str


class BootstrapResponse(BaseModel):
    node_id: uuid.UUID
    minion_id: str
    job_id: str
    bootstrap_status: str
    message: str


class PlatformSettingsUpdate(BaseModel):
    salt_master_address: str | None = None
    ssh_bootstrap_username: str | None = None
    ssh_bootstrap_password: str | None = None


class PlatformSettingsResponse(BaseModel):
    salt_master_address: str | None
    ssh_bootstrap_username: str | None
    ssh_bootstrap_password: None = None
    controller_pubkey: str | None
