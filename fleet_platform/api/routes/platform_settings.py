# fleet_platform/api/routes/platform_settings.py
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.api.deps import get_db
from fleet_platform.core.auth import require_role
from fleet_platform.schemas.ansible import PlatformSettingsResponse, PlatformSettingsUpdate
from fleet_platform.services.platform_settings_svc import (
    ANSIBLE_API_TOKEN,
    ANSIBLE_ENDPOINT_URL,
    CXONE_API_TOKEN,
    CXONE_URL,
    DIGEST_RECIPIENTS,
    JENKINS_INGEST_SECRET,
    KRI_API_URL,
    LICENSE_POLICY,
    OIDC_CLIENT_ID,
    OIDC_CLIENT_SECRET,
    OIDC_ENABLED,
    OIDC_ISSUER_URL,
    OIDC_ROLE_PREFIX,
    PILLAR_DIR,
    PLAYBOOKS_DIR,
    SALT_MASTER,
    SMTP_FROM,
    SMTP_HOST,
    SMTP_PASSWORD,
    SMTP_PORT,
    SMTP_USERNAME,
    SONARQUBE_TOKEN,
    SONARQUBE_URL,
    SSH_PASSWORD,
    SSH_USERNAME,
    VNC_ENABLED,
    get_setting,
    set_setting,
)
from fleet_platform.services.ssh_keypair import ensure_controller_keypair, get_controller_pubkey

router = APIRouter(prefix="/api/v1/settings")


@router.get("", response_model=PlatformSettingsResponse)
async def get_settings(
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("admin")),
):
    ensure_controller_keypair()
    vnc_enabled_raw = await get_setting(db, VNC_ENABLED)
    vnc_enabled = vnc_enabled_raw == "true"
    oidc_enabled_raw = await get_setting(db, OIDC_ENABLED)
    oidc_enabled = oidc_enabled_raw == "true"
    return PlatformSettingsResponse(
        salt_master_address=await get_setting(db, SALT_MASTER),
        kri_api_url=await get_setting(db, KRI_API_URL),
        ssh_bootstrap_username=await get_setting(db, SSH_USERNAME),
        controller_pubkey=get_controller_pubkey(),
        ansible_endpoint_url=await get_setting(db, ANSIBLE_ENDPOINT_URL),
        playbooks_dir=await get_setting(db, PLAYBOOKS_DIR),
        pillar_dir=await get_setting(db, PILLAR_DIR),
        cxone_url=await get_setting(db, CXONE_URL),
        sonarqube_url=await get_setting(db, SONARQUBE_URL),
        license_policy=await get_setting(db, LICENSE_POLICY),
        vnc_enabled=vnc_enabled,
        oidc_enabled=oidc_enabled,
        oidc_issuer_url=await get_setting(db, OIDC_ISSUER_URL),
        oidc_client_id=await get_setting(db, OIDC_CLIENT_ID),
        oidc_role_prefix=await get_setting(db, OIDC_ROLE_PREFIX),
        smtp_host=await get_setting(db, SMTP_HOST),
        smtp_port=await get_setting(db, SMTP_PORT),
        smtp_username=await get_setting(db, SMTP_USERNAME),
        smtp_from=await get_setting(db, SMTP_FROM),
        digest_recipients=await get_setting(db, DIGEST_RECIPIENTS),
    )


@router.put("", response_model=PlatformSettingsResponse)
async def update_settings(
    payload: PlatformSettingsUpdate,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("admin")),
):
    ensure_controller_keypair()
    if payload.salt_master_address is not None:
        await set_setting(db, SALT_MASTER, payload.salt_master_address)
    if payload.kri_api_url is not None:
        await set_setting(db, KRI_API_URL, payload.kri_api_url)
    if payload.ssh_bootstrap_username is not None:
        await set_setting(db, SSH_USERNAME, payload.ssh_bootstrap_username)
    if payload.ssh_bootstrap_password is not None:
        await set_setting(db, SSH_PASSWORD, payload.ssh_bootstrap_password, encrypt=True)
    if payload.ansible_endpoint_url is not None:
        await set_setting(db, ANSIBLE_ENDPOINT_URL, payload.ansible_endpoint_url)
    if payload.ansible_api_token:
        await set_setting(db, ANSIBLE_API_TOKEN, payload.ansible_api_token, encrypt=True)
    if payload.playbooks_dir is not None:
        await set_setting(db, PLAYBOOKS_DIR, payload.playbooks_dir)
    if payload.pillar_dir is not None:
        await set_setting(db, PILLAR_DIR, payload.pillar_dir)
    if payload.cxone_url is not None:
        await set_setting(db, CXONE_URL, payload.cxone_url)
    if payload.cxone_api_token:
        await set_setting(db, CXONE_API_TOKEN, payload.cxone_api_token, encrypt=True)
    if payload.sonarqube_url is not None:
        await set_setting(db, SONARQUBE_URL, payload.sonarqube_url)
    if payload.sonarqube_token:
        await set_setting(db, SONARQUBE_TOKEN, payload.sonarqube_token, encrypt=True)
    if payload.license_policy is not None:
        await set_setting(db, LICENSE_POLICY, payload.license_policy)
    if payload.vnc_enabled is not None:
        await set_setting(db, VNC_ENABLED, "true" if payload.vnc_enabled else "false")
    if payload.oidc_enabled is not None:
        await set_setting(db, OIDC_ENABLED, "true" if payload.oidc_enabled else "false")
    if payload.oidc_issuer_url is not None:
        await set_setting(db, OIDC_ISSUER_URL, payload.oidc_issuer_url)
    if payload.oidc_client_id is not None:
        await set_setting(db, OIDC_CLIENT_ID, payload.oidc_client_id)
    if payload.oidc_client_secret:
        await set_setting(db, OIDC_CLIENT_SECRET, payload.oidc_client_secret, encrypt=True)
    if payload.oidc_role_prefix is not None:
        await set_setting(db, OIDC_ROLE_PREFIX, payload.oidc_role_prefix)
    if payload.smtp_host is not None:
        await set_setting(db, SMTP_HOST, payload.smtp_host)
    if payload.smtp_port is not None:
        await set_setting(db, SMTP_PORT, payload.smtp_port)
    if payload.smtp_username is not None:
        await set_setting(db, SMTP_USERNAME, payload.smtp_username)
    if payload.smtp_password:
        await set_setting(db, SMTP_PASSWORD, payload.smtp_password, encrypt=True)
    if payload.smtp_from is not None:
        await set_setting(db, SMTP_FROM, payload.smtp_from)
    if payload.digest_recipients is not None:
        await set_setting(db, DIGEST_RECIPIENTS, payload.digest_recipients)
    if payload.jenkins_ingest_secret:
        await set_setting(db, JENKINS_INGEST_SECRET, payload.jenkins_ingest_secret, encrypt=True)
    vnc_enabled_raw = await get_setting(db, VNC_ENABLED)
    vnc_enabled = vnc_enabled_raw == "true"
    oidc_enabled_raw = await get_setting(db, OIDC_ENABLED)
    oidc_enabled = oidc_enabled_raw == "true"
    return PlatformSettingsResponse(
        salt_master_address=await get_setting(db, SALT_MASTER),
        kri_api_url=await get_setting(db, KRI_API_URL),
        ssh_bootstrap_username=await get_setting(db, SSH_USERNAME),
        controller_pubkey=get_controller_pubkey(),
        ansible_endpoint_url=await get_setting(db, ANSIBLE_ENDPOINT_URL),
        playbooks_dir=await get_setting(db, PLAYBOOKS_DIR),
        pillar_dir=await get_setting(db, PILLAR_DIR),
        cxone_url=await get_setting(db, CXONE_URL),
        sonarqube_url=await get_setting(db, SONARQUBE_URL),
        license_policy=await get_setting(db, LICENSE_POLICY),
        vnc_enabled=vnc_enabled,
        oidc_enabled=oidc_enabled,
        oidc_issuer_url=await get_setting(db, OIDC_ISSUER_URL),
        oidc_client_id=await get_setting(db, OIDC_CLIENT_ID),
        oidc_role_prefix=await get_setting(db, OIDC_ROLE_PREFIX),
        smtp_host=await get_setting(db, SMTP_HOST),
        smtp_port=await get_setting(db, SMTP_PORT),
        smtp_username=await get_setting(db, SMTP_USERNAME),
        smtp_from=await get_setting(db, SMTP_FROM),
        digest_recipients=await get_setting(db, DIGEST_RECIPIENTS),
    )
