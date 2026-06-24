# fleet_platform/schemas/ansible.py
import re
import uuid

from pydantic import BaseModel, field_validator

from fleet_platform.core.validators import validate_minion_id

_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
_LISTEN_ADDR_RE = re.compile(r"^[\w.\-]*:\d{1,5}$")


class BootstrapRequest(BaseModel):
    minion_id: str

    _validate_minion_id = field_validator("minion_id")(validate_minion_id)
    target_ip: str
    ssh_username: str | None = None  # overrides platform setting ssh_bootstrap_username
    ssh_password: str | None = None  # overrides platform setting ssh_bootstrap_password
    ssh_key: str | None = None  # plaintext private key for key-based auth
    salt_master_ids: list[str] | None = None  # HA: specific master IDs to use; None → all enabled
    # Runtime overrides for #830 (all optional; omitted → playbook/group_vars defaults apply)
    node_exporter_version: str | None = None
    node_exporter_listen_address: str | None = None
    node_exporter_url_override: str | None = None
    bootstrap_full: bool | None = None

    @field_validator("node_exporter_version")
    @classmethod
    def validate_node_exporter_version(cls, v: str | None) -> str | None:
        if v is not None and not _VERSION_RE.match(v):
            raise ValueError(f"node_exporter_version must match X.Y.Z (got {v!r})")
        return v

    @field_validator("node_exporter_listen_address")
    @classmethod
    def validate_node_exporter_listen_address(cls, v: str | None) -> str | None:
        if v is not None and not _LISTEN_ADDR_RE.match(v):
            raise ValueError(
                f"node_exporter_listen_address must match [host]:port, e.g. ':9100' or '0.0.0.0:9100' (got {v!r})"
            )
        return v


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
