# fleet_platform/schemas/ansible.py
import uuid
from pydantic import BaseModel


class BootstrapRequest(BaseModel):
    minion_id: str
    target_ip: str
    ssh_username: str | None = None   # overrides platform setting ssh_bootstrap_username
    ssh_password: str | None = None   # overrides platform setting ssh_bootstrap_password
    ssh_key: str | None = None        # plaintext private key for key-based auth


class BootstrapResponse(BaseModel):
    node_id: uuid.UUID
    minion_id: str
    job_id: str
    bootstrap_status: str
    message: str


class PlatformSettingsUpdate(BaseModel):
    salt_master_address: str | None = None
    kri_api_url: str | None = None
    ssh_bootstrap_username: str | None = None
    ssh_bootstrap_password: str | None = None
    ansible_endpoint_url: str | None = None
    ansible_api_token: str | None = None
    playbooks_dir: str | None = None
    pillar_dir: str | None = None


class PlatformSettingsResponse(BaseModel):
    salt_master_address: str | None
    kri_api_url: str | None = None
    ssh_bootstrap_username: str | None
    ssh_bootstrap_password: None = None
    controller_pubkey: str | None
    ansible_endpoint_url: str | None = None
    ansible_api_token: None = None
    playbooks_dir: str | None = None
    pillar_dir: str | None = None
