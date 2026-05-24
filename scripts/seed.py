#!/usr/bin/env python3
"""Seed default users. Run with: docker exec deploy-api-1 uv run python3 /app/scripts/seed.py"""
import asyncio
from fleet_platform.core.auth import hash_password
from fleet_platform.core.config import settings
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy import text

USERS = [
    ("admin@fleet.local",  "changeme", "admin"),
    ("viewer@fleet.local", "changeme", "viewer"),
    ("admin@admin.com",    "changeme", "admin"),
]


async def main() -> None:
    engine = create_async_engine(settings.database_url)
    async with AsyncSession(engine) as s:
        for email, pw, role in USERS:
            await s.execute(
                text(
                    "INSERT INTO users (id,email,password_hash,role,is_active,created_at,updated_at)"
                    " VALUES (gen_random_uuid(),:e,:h,:r,true,now(),now())"
                    " ON CONFLICT (email) DO UPDATE SET password_hash=:h, role=:r"
                ),
                {"e": email, "h": hash_password(pw), "r": role},
            )
        await s.commit()
        rows = (await s.execute(text("SELECT email, role FROM users ORDER BY email"))).all()
        print(f"Seeded {len(rows)} users:")
        for row in rows:
            print(f"  {row.email}  ({row.role})  password=changeme")


asyncio.run(main())
