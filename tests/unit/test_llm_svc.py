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
