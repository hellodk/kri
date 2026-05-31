"""Unit tests for llm_svc.update_endpoint provider handling (#277)."""
from unittest.mock import AsyncMock

import pytest

from fleet_platform.models.llm_endpoint import LLMEndpoint
from fleet_platform.schemas.llm import LLMEndpointUpdate
from fleet_platform.services import llm_svc


def _fake_db():
    db = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.execute = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_update_endpoint_changes_provider():
    endpoint = LLMEndpoint(
        name="exo-open-ai", provider="ollama",
        base_url="http://192.168.1.23:52415/v1", model="m",
    )
    payload = LLMEndpointUpdate(provider="openai_compat")
    await llm_svc.update_endpoint(_fake_db(), endpoint, payload)
    assert endpoint.provider == "openai_compat"


@pytest.mark.asyncio
async def test_update_endpoint_leaves_provider_when_omitted():
    endpoint = LLMEndpoint(
        name="exo", provider="openai_compat",
        base_url="http://192.168.1.23:52415", model="m",
    )
    payload = LLMEndpointUpdate(name="renamed")  # no provider
    await llm_svc.update_endpoint(_fake_db(), endpoint, payload)
    assert endpoint.provider == "openai_compat"
    assert endpoint.name == "renamed"


@pytest.mark.asyncio
async def test_list_endpoints_calls_db():
    from unittest.mock import MagicMock
    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    db.execute = AsyncMock(return_value=mock_result)
    result = await llm_svc.list_endpoints(db)
    assert result == []
    db.execute.assert_called_once()


@pytest.mark.asyncio
async def test_get_default_endpoint_returns_none_when_missing():
    from unittest.mock import MagicMock
    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=mock_result)
    result = await llm_svc.get_default_endpoint(db)
    assert result is None


@pytest.mark.asyncio
async def test_delete_endpoint_commits():
    from unittest.mock import MagicMock
    endpoint = MagicMock()
    db = AsyncMock()
    db.delete = AsyncMock()
    db.commit = AsyncMock()
    await llm_svc.delete_endpoint(db, endpoint)
    db.delete.assert_called_once_with(endpoint)
    db.commit.assert_called_once()
