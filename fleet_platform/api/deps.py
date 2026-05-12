from collections.abc import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession
from fleet_platform.db.session import AsyncSessionLocal


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
