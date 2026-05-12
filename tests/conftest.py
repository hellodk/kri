# tests/conftest.py
import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
async def client():
    from fleet_platform.api.main import create_app
    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as ac:
        yield ac
