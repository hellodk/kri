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
    KRI_API_URL,
    LICENSE_POLICY,
    PILLAR_DIR,
    PLAYBOOKS_DIR,
    SALT_MASTER,
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
    vnc_enabled_raw = await get_setting(db, VNC_ENABLED)
    vnc_enabled = vnc_enabled_raw == "true"
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
    )
