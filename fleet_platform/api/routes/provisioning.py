import re
import uuid
from datetime import UTC, datetime
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.api.deps import get_db
from fleet_platform.core.auth import require_role
from fleet_platform.models.provisioning import ProvisioningProfile
from fleet_platform.schemas.provisioning import ProvisioningProfileList, ProvisioningProfileResponse

router = APIRouter(prefix="/api/v1/provisioning")

MAX_PROFILE_SIZE = 5 * 1024 * 1024  # 5 MB


def _safe_filename(name: str) -> str:
    # Strip control chars, quotes, backslashes, and forward slashes (path traversal)
    return re.sub(r'[\x00-\x1f\x7f"\\\/]', '_', name)


def _parse_profile_metadata(content: bytes) -> dict:
    """Extract bundle_id, team_name, expiry_date, profile_type from .mobileprovision binary.

    A .mobileprovision file is a CMS-signed plist. The embedded plist is extracted
    by searching for the XML content between <?xml and </plist>.
    """
    import plistlib
    import re

    match = re.search(b"<\\?xml.*?</plist>", content, re.DOTALL)
    if not match:
        return {}
    try:
        plist = plistlib.loads(match.group())
        expiry = plist.get("ExpirationDate")
        ents = plist.get("Entitlements", {})
        bundle = ents.get("application-identifier", "").split(".", 1)[-1] or plist.get("AppIDName")
        team = plist.get("TeamName")
        # Determine profile type
        provisions_devices = plist.get("ProvisionedDevices")
        get_task_allow = ents.get("get-task-allow", False)
        if get_task_allow:
            profile_type = "development"
        elif provisions_devices:
            profile_type = "adhoc"
        else:
            profile_type = "distribution"
        return {
            "bundle_id": bundle or None,
            "team_name": team or None,
            "expiry_date": expiry,
            "profile_type": profile_type,
        }
    except Exception:
        return {}


@router.post("", response_model=ProvisioningProfileResponse, status_code=201)
async def upload_profile(
    name: str = Form(...),
    description: Optional[str] = Form(None),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_role("operator", "admin")),
):
    if not file.filename or not file.filename.endswith(".mobileprovision"):
        raise HTTPException(status_code=400, detail="File must be a .mobileprovision file")

    content = await file.read()
    if len(content) > MAX_PROFILE_SIZE:
        raise HTTPException(status_code=413, detail="Profile file too large (max 5 MB)")

    meta = _parse_profile_metadata(content)

    profile = ProvisioningProfile(
        name=name,
        filename=file.filename,
        content=content,
        description=description,
        uploaded_by=claims["email"],
        bundle_id=meta.get("bundle_id"),
        team_name=meta.get("team_name"),
        expiry_date=meta.get("expiry_date"),
        profile_type=meta.get("profile_type", "development"),
        created_at=datetime.now(UTC),
    )
    db.add(profile)
    await db.commit()
    await db.refresh(profile)
    return ProvisioningProfileResponse.model_validate(profile)


@router.get("", response_model=ProvisioningProfileList)
async def list_profiles(
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("viewer", "operator", "admin")),
):
    result = await db.execute(
        select(ProvisioningProfile).order_by(ProvisioningProfile.created_at.desc())
    )
    profiles = result.scalars().all()
    total = await db.scalar(select(func.count()).select_from(ProvisioningProfile))
    return ProvisioningProfileList(
        items=[ProvisioningProfileResponse.model_validate(p) for p in profiles],
        total=total or 0,
    )


@router.get("/{profile_id}/download")
async def download_profile(
    profile_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("viewer", "operator", "admin")),
):
    from fastapi.responses import Response

    result = await db.execute(
        select(ProvisioningProfile).where(ProvisioningProfile.id == profile_id)
    )
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    return Response(
        content=profile.content,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{_safe_filename(profile.filename)}"'},
    )


@router.delete("/{profile_id}", status_code=204)
async def delete_profile(
    profile_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("operator", "admin")),
):
    result = await db.execute(
        select(ProvisioningProfile).where(ProvisioningProfile.id == profile_id)
    )
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    await db.delete(profile)
    await db.commit()
