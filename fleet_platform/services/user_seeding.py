"""Seed permanent local accounts from environment variables at startup.

Reads:
  SEED_LOCAL_ADMIN_EMAIL     — admin email (required for seeding)
  SEED_LOCAL_ADMIN_PASSWORD  — admin password (required for seeding)
  SEED_LOCAL_USER_n_EMAIL    — extra user email (n = 1, 2, 3...)
  SEED_LOCAL_USER_n_PASSWORD — extra user password
  SEED_LOCAL_USER_n_ROLE     — extra user role (default: viewer)
"""
import os

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.core.auth import hash_password
from fleet_platform.models.user import User

_VALID_ROLES = {"admin", "operator", "viewer", "auditor"}


async def seed_local_users(db: AsyncSession) -> None:
    accounts = []

    admin_email = os.environ.get("SEED_LOCAL_ADMIN_EMAIL", "").strip()
    admin_password = os.environ.get("SEED_LOCAL_ADMIN_PASSWORD", "").strip()
    if admin_email and admin_password:
        accounts.append((admin_email, admin_password, "admin"))

    n = 1
    while True:
        email = os.environ.get(f"SEED_LOCAL_USER_{n}_EMAIL", "").strip()
        password = os.environ.get(f"SEED_LOCAL_USER_{n}_PASSWORD", "").strip()
        if not email or not password:
            break
        role = os.environ.get(f"SEED_LOCAL_USER_{n}_ROLE", "viewer").strip()
        if role not in _VALID_ROLES:
            role = "viewer"
        accounts.append((email, password, role))
        n += 1

    if not accounts:
        return

    for email, password, role in accounts:
        result = await db.execute(select(User).where(User.email == email))
        if result.scalar_one_or_none() is not None:
            continue
        db.add(User(
            email=email,
            password_hash=hash_password(password),
            role=role,
            is_active=True,
            auth_provider="local",
        ))

    await db.commit()
