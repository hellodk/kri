"""Unit tests for fleet-wide AI recommendations (#4).

Replaces the per-node "Ask AI" quick-fix (#294) with a stored, fleet-wide
recommendation feed generated daily (Celery beat) and on-demand (API).
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fleet_platform.models.fleet_recommendation import FleetRecommendation
from fleet_platform.services import fleet_recommendations_svc


def _fake_endpoint(provider="anthropic", enabled=True):
    endpoint = MagicMock()
    endpoint.enabled = enabled
    endpoint.provider = provider
    endpoint.model = "claude-3-5-sonnet"
    endpoint.base_url = "https://api.anthropic.com"
    endpoint.model_context_length = None
    endpoint.model_capabilities = None
    endpoint.api_key_encrypted = None
    return endpoint


def _fake_db(node_count=3):
    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    count_result = MagicMock()
    count_result.scalar_one.return_value = node_count
    db.execute = AsyncMock(return_value=count_result)
    return db


# --------------------------------------------------------------------------
# Service: generate_fleet_recommendations
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_persists_row_with_expected_fields():
    db = _fake_db(node_count=5)
    endpoint = _fake_endpoint(provider="anthropic")

    with (
        patch.object(fleet_recommendations_svc, "get_default_endpoint", AsyncMock(return_value=endpoint)),
        patch.object(
            fleet_recommendations_svc,
            "build_fleet_context",
            AsyncMock(return_value=("fleet context text", [])),
        ),
        patch.object(fleet_recommendations_svc, "get_decrypted_api_key", return_value="sk-test"),
        patch.object(
            fleet_recommendations_svc,
            "call_anthropic",
            AsyncMock(return_value=("## Reliability\n- Node x is flaky", 100, 50)),
        ) as mock_call,
    ):
        result = await fleet_recommendations_svc.generate_fleet_recommendations(db, generated_by="ops@example.com")

    assert isinstance(result, FleetRecommendation)
    assert result.content == "## Reliability\n- Node x is flaky"
    assert result.model == "claude-3-5-sonnet"
    assert result.provider == "anthropic"
    assert result.node_count == 5
    assert result.generated_by == "ops@example.com"
    db.add.assert_called_once_with(result)
    db.commit.assert_awaited_once()
    mock_call.assert_awaited_once()


@pytest.mark.asyncio
async def test_generate_uses_openai_compat_for_non_anthropic_provider():
    db = _fake_db(node_count=2)
    endpoint = _fake_endpoint(provider="openai_compat")

    with (
        patch.object(fleet_recommendations_svc, "get_default_endpoint", AsyncMock(return_value=endpoint)),
        patch.object(
            fleet_recommendations_svc,
            "build_fleet_context",
            AsyncMock(return_value=("fleet context text", [])),
        ),
        patch.object(fleet_recommendations_svc, "get_decrypted_api_key", return_value=None),
        patch.object(
            fleet_recommendations_svc,
            "call_openai_compat",
            AsyncMock(return_value=("## Drift\n- Node y drifted", 10, 5)),
        ) as mock_call,
        patch.object(fleet_recommendations_svc, "call_anthropic", AsyncMock()) as mock_anthropic,
    ):
        result = await fleet_recommendations_svc.generate_fleet_recommendations(db, generated_by="schedule")

    assert result.provider == "openai_compat"
    mock_call.assert_awaited_once()
    mock_anthropic.assert_not_awaited()


@pytest.mark.asyncio
async def test_generate_raises_when_no_endpoint_configured():
    db = _fake_db()

    with patch.object(fleet_recommendations_svc, "get_default_endpoint", AsyncMock(return_value=None)):
        with pytest.raises(ValueError, match="No LLM endpoint configured"):
            await fleet_recommendations_svc.generate_fleet_recommendations(db, generated_by="schedule")


@pytest.mark.asyncio
async def test_generate_raises_when_endpoint_disabled():
    db = _fake_db()
    endpoint = _fake_endpoint(enabled=False)

    with patch.object(fleet_recommendations_svc, "get_default_endpoint", AsyncMock(return_value=endpoint)):
        with pytest.raises(ValueError, match="No LLM endpoint configured"):
            await fleet_recommendations_svc.generate_fleet_recommendations(db, generated_by="schedule")


# --------------------------------------------------------------------------
# Service: get_latest_recommendation
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_latest_returns_newest():
    newest = FleetRecommendation(
        id=uuid.uuid4(),
        generated_at=datetime.now(UTC),
        content="latest",
        model="m",
        node_count=1,
        provider="anthropic",
        generated_by="schedule",
    )
    db = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = newest
    db.execute = AsyncMock(return_value=result_mock)

    result = await fleet_recommendations_svc.get_latest_recommendation(db)

    assert result is newest


@pytest.mark.asyncio
async def test_get_latest_returns_none_when_empty():
    db = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=result_mock)

    result = await fleet_recommendations_svc.get_latest_recommendation(db)

    assert result is None


# --------------------------------------------------------------------------
# API endpoints
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_recommendations_endpoint_returns_latest():
    from fleet_platform.api.routes.recommendations import get_recommendations

    latest = FleetRecommendation(
        id=uuid.uuid4(),
        generated_at=datetime.now(UTC),
        content="the recs",
        model="m",
        node_count=4,
        provider="anthropic",
        generated_by="ops@example.com",
    )
    response = MagicMock()
    db = AsyncMock()

    with patch(
        "fleet_platform.api.routes.recommendations.get_latest_recommendation",
        AsyncMock(return_value=latest),
    ):
        result = await get_recommendations(response=response, db=db, _claims={})

    assert result.content == "the recs"
    assert result.node_count == 4


@pytest.mark.asyncio
async def test_get_recommendations_endpoint_returns_none_when_empty():
    from fastapi import status

    from fleet_platform.api.routes.recommendations import get_recommendations

    response = MagicMock()
    db = AsyncMock()

    with patch(
        "fleet_platform.api.routes.recommendations.get_latest_recommendation",
        AsyncMock(return_value=None),
    ):
        result = await get_recommendations(response=response, db=db, _claims={})

    assert result is None
    assert response.status_code == status.HTTP_204_NO_CONTENT


@pytest.mark.asyncio
async def test_generate_recommendations_endpoint_calls_service():
    from fleet_platform.api.limiter import limiter
    from fleet_platform.api.routes.recommendations import generate_recommendations

    generated = FleetRecommendation(
        id=uuid.uuid4(),
        generated_at=datetime.now(UTC),
        content="fresh recs",
        model="m",
        node_count=7,
        provider="anthropic",
        generated_by="ops@example.com",
    )
    request = MagicMock()
    db = AsyncMock()
    claims = {"email": "ops@example.com"}

    # Rate limiting is exercised end-to-end elsewhere (test_llm_rate_limit.py checks
    # the decorator is applied); disable it here so a bare MagicMock request doesn't
    # need to satisfy slowapi's internal Request/state machinery.
    previously_enabled = limiter.enabled
    limiter.enabled = False
    try:
        with patch(
            "fleet_platform.api.routes.recommendations.generate_fleet_recommendations",
            AsyncMock(return_value=generated),
        ) as mock_generate:
            result = await generate_recommendations(request=request, db=db, claims=claims)
    finally:
        limiter.enabled = previously_enabled

    mock_generate.assert_awaited_once_with(db, generated_by="ops@example.com")
    assert result.content == "fresh recs"


@pytest.mark.asyncio
async def test_generate_recommendations_endpoint_raises_422_on_no_endpoint():
    from fastapi import HTTPException

    from fleet_platform.api.limiter import limiter
    from fleet_platform.api.routes.recommendations import generate_recommendations

    request = MagicMock()
    db = AsyncMock()
    claims = {"email": "ops@example.com"}

    previously_enabled = limiter.enabled
    limiter.enabled = False
    try:
        with patch(
            "fleet_platform.api.routes.recommendations.generate_fleet_recommendations",
            AsyncMock(side_effect=ValueError("No LLM endpoint configured.")),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await generate_recommendations(request=request, db=db, claims=claims)
    finally:
        limiter.enabled = previously_enabled

    assert exc_info.value.status_code == 422


# --------------------------------------------------------------------------
# Route registration: /ask-ai is gone
# --------------------------------------------------------------------------


def test_ask_ai_route_no_longer_registered():
    """The old per-node /ask-ai route must not exist — replaced by fleet-wide recommendations."""
    from fleet_platform.api.routes.node_actions import router

    paths = [r.path for r in router.routes]
    assert not any("ask-ai" in p for p in paths), f"ask-ai route still present in {paths}"
