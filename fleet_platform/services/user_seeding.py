"""Seed permanent local accounts from environment variables at startup.

Reads:
  SEED_LOCAL_ADMIN_EMAIL     — admin email (required for seeding)
  SEED_LOCAL_ADMIN_PASSWORD  — admin password (required for seeding)
  SEED_LOCAL_USER_n_EMAIL    — extra user email (n = 1, 2, 3...)
  SEED_LOCAL_USER_n_PASSWORD — extra user password
  SEED_LOCAL_USER_n_ROLE     — extra user role (default: viewer)

Weak-password policy (#757/#820):
  Non-development environments: seeding is refused when the admin password
    matches a known-weak pattern (dictionary words, short strings).  This
    prevents "admin/admin" from ever reaching a production deployment.
  Development environment: seeding is allowed but the account is flagged
    with must_change_password=True so the operator is forced to change it
    on first login.
"""

import os

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.core.auth import hash_password
from fleet_platform.models.user import User

_VALID_ROLES = {"admin", "operator", "viewer", "auditor"}

# Passwords that are unacceptable in any environment other than a one-time
# dev bootstrap (must be changed immediately after first login).
_WEAK_PASSWORDS: frozenset[str] = frozenset(
    {
        "admin",
        "password",
        "123456",
        "12345678",
        "admin123",
        "changeme",
        "password1",
        "qwerty",
        "letmein",
        "welcome",
        "test",
        "root",
        "toor",
        "pass",
    }
)

# Minimum length for a non-weak password (NIST SP 800-63B guidance).
_MIN_PASSWORD_LENGTH = 12


def _is_weak_password(password: str) -> bool:
    return password.lower() in _WEAK_PASSWORDS or len(password) < _MIN_PASSWORD_LENGTH


async def seed_local_users(db: AsyncSession) -> None:
    from fleet_platform.core.config import settings

    accounts = []

    admin_email = os.environ.get("SEED_LOCAL_ADMIN_EMAIL", "").strip()
    admin_password = os.environ.get("SEED_LOCAL_ADMIN_PASSWORD", "").strip()
    if admin_email and admin_password:
        if _is_weak_password(admin_password):
            if not settings.is_development:
                raise RuntimeError(
                    "SEED_LOCAL_ADMIN_PASSWORD is too weak for a non-development environment. "
                    "Use a password of at least 12 characters that is not a common word. "
                    "Set SEED_LOCAL_ADMIN_PASSWORD to a strong value before starting the service. "
                    "(#757/#820)"
                )
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
        must_change = _is_weak_password(password)
        db.add(
            User(
                email=email,
                password_hash=hash_password(password),
                role=role,
                is_active=True,
                auth_provider="local",
                must_change_password=must_change,
            )
        )

    await db.commit()
