# fleet_platform/schemas/ansible.py
import uuid

from pydantic import BaseModel


class BootstrapRequest(BaseModel):
    minion_id: str
    target_ip: str
    ssh_username: str | None = None  # overrides platform setting ssh_bootstrap_username
    ssh_password: str | None = None  # overrides platform setting ssh_bootstrap_password
    ssh_key: str | None = None  # plaintext private key for key-based auth
    salt_master_ids: list[str] | None = None  # HA: specific master IDs to use; None → all enabled


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
    cxone_url: str | None = None
    cxone_api_token: str | None = None
    sonarqube_url: str | None = None
    sonarqube_token: str | None = None
    license_policy: str | None = None
    vnc_enabled: bool = False
    oidc_enabled: bool | None = None
    oidc_issuer_url: str | None = None
    oidc_client_id: str | None = None
    oidc_client_secret: str | None = None
    oidc_role_prefix: str | None = None
    # Email digest
    smtp_host: str | None = None
    smtp_port: str | None = None
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from: str | None = None
    digest_recipients: str | None = None
    # Jenkins
    jenkins_ingest_secret: str | None = None
    # Salt allowlist / denylist
    salt_allowed_functions: list[str] | None = None
    salt_denied_functions: list[str] | None = None
    # RAG embedding
    llm_embed_base_url: str | None = None
    llm_include_node_ips: bool | None = None


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
    cxone_url: str | None = None
    sonarqube_url: str | None = None
    license_policy: str | None = None
    vnc_enabled: bool = False
    oidc_enabled: bool = False
    oidc_issuer_url: str | None = None
    oidc_client_id: str | None = None
    oidc_client_secret: None = None
    oidc_role_prefix: str | None = None
    # Email digest (never return secrets)
    smtp_host: str | None = None
    smtp_port: str | None = None
    smtp_username: str | None = None
    smtp_password: None = None
    smtp_from: str | None = None
    digest_recipients: str | None = None
    # Jenkins (never return secret)
    jenkins_ingest_secret: None = None
    # Salt allowlist / denylist
    salt_allowed_functions: list[str] | None = None
    salt_denied_functions: list[str] | None = None
    # RAG embedding
    llm_embed_base_url: str | None = None
    llm_include_node_ips: bool = True
