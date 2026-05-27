#!/usr/bin/env python3
"""Create initial admin user. Run with:
    docker exec deploy-api-1 uv run python3 /app/scripts/seed_users.py

This script creates an admin account with a randomly generated password
printed to stdout. Change it via the Settings UI after first login.

DO NOT use the old seed.py — it creates accounts with a hardcoded
insecure password. That script has been removed.
"""
import asyncio
import secrets
import string

from fleet_platform.core.auth import hash_password
from fleet_platform.core.config import settings
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy import text


def _generate_password(length: int = 20) -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    return "".join(secrets.choice(alphabet) for _ in range(length))


async def main() -> None:
    engine = create_async_engine(settings.database_url)
    async with AsyncSession(engine) as s:
        email = "admin@fleet.local"
        password = _generate_password()
        await s.execute(
            text(
                "INSERT INTO users (id,email,password_hash,role,is_active,created_at,updated_at)"
                " VALUES (gen_random_uuid(),:e,:h,'admin',true,now(),now())"
                " ON CONFLICT (email) DO NOTHING"
            ),
            {"e": email, "h": hash_password(password)},
        )
        await s.commit()
        print(f"\n{'='*50}")
        print(f"Admin account created:")
        print(f"  Email:    {email}")
        print(f"  Password: {password}")
        print(f"  IMPORTANT: Save this password — it will not be shown again.")
        print(f"{'='*50}\n")


asyncio.run(main())
