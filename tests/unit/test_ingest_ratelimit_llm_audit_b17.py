"""Unit tests for #168 (ingest rate limit) and #170 (LLM audit trail).

Behavioral replacements for the original source-scrape assertions:
  - test_ingest_has_rate_limit: was '"_check_ingest_rate_limit" in INGEST'
    → drives _check_ingest_rate_limit directly with mocked Redis
  - test_ingest_rate_limit_fails_open: was 'except" in INGEST and "return True"'
    → drives _check_ingest_rate_limit with Redis raising; asserts 503 (fail-closed
    is the actual behavior since #768 — original test was asserting wrong behavior)
  - test_llm_queries_logged_to_audit: was '"audit" in LLM.lower()'
    → drives submit_query via ASGI with mocked deps; asserts audit() is called
    with action="llm_query"
"""

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import fleet_platform.api.routes.ingest as _ingest_mod


def _make_redis_mock(count: int = 1):
    """Return (mock_redis, mock_pipe) backed by an async pipeline execute."""
    mock_pipe = MagicMock()
    mock_pipe.execute = AsyncMock(return_value=[count, True])
    mock_redis = MagicMock()
    mock_redis.pipeline.return_value = mock_pipe
    return mock_redis, mock_pipe


def test_ingest_has_rate_limit():
    """Rate limiter must deny when count exceeds _INGEST_RATE_LIMIT and allow when within it (#168).

    Also verifies that Redis INCR is used for atomic counting — if it weren't called,
    the pipeline-based rate window would be broken.
    """

    async def _run():
        r_over, _ = _make_redis_mock(_ingest_mod._INGEST_RATE_LIMIT + 1)
        with patch.object(_ingest_mod, "get_redis", AsyncMock(return_value=r_over)):
            denied = await _ingest_mod._check_ingest_rate_limit("node-over")
        assert denied is False, "must deny when count > _INGEST_RATE_LIMIT"

        r_ok, pipe_ok = _make_redis_mock(1)
        with patch.object(_ingest_mod, "get_redis", AsyncMock(return_value=r_ok)):
            allowed = await _ingest_mod._check_ingest_rate_limit("node-ok")
        assert allowed is True, "must allow when count <= _INGEST_RATE_LIMIT"

        r_incr, pipe_incr = _make_redis_mock(1)
        with patch.object(_ingest_mod, "get_redis", AsyncMock(return_value=r_incr)):
            await _ingest_mod._check_ingest_rate_limit("node-incr")
        pipe_incr.incr.assert_called_once(), "rate limit must use Redis INCR for atomic counting"

    asyncio.run(_run())


def test_ingest_rate_limit_fails_closed_on_redis_error():
    """When Redis is unreachable, the rate limiter must raise HTTP 503 and block the request.

    The behavior is fail-CLOSED (503) since #768 — ingest is denied when the rate-limit
    store is down to prevent uncontrolled spikes during Redis outages.
    """
    from fastapi import HTTPException

    async def _run():
        with patch.object(_ingest_mod, "get_redis", AsyncMock(side_effect=Exception("redis down"))):
            try:
                await _ingest_mod._check_ingest_rate_limit("node-err")
                raise AssertionError("Expected HTTPException 503 when Redis fails — none was raised")
            except HTTPException as exc:
                assert exc.status_code == 503, f"Redis failure must yield 503 (fail-closed), got {exc.status_code}"

    asyncio.run(_run())


def test_llm_queries_logged_to_audit():
    """submit_query must call audit() with action='llm_query' on every successful LLM call (#170)."""

    async def _run():
        from httpx import ASGITransport, AsyncClient

        from fleet_platform.api import deps
        from fleet_platform.api.limiter import limiter
        from fleet_platform.api.main import create_app
        from fleet_platform.core.auth import create_access_token

        limiter._storage.reset()
        app = create_app()

        mock_db_session = AsyncMock()
        mock_db_session.execute = AsyncMock(return_value=MagicMock())
        mock_db_session.commit = AsyncMock()
        mock_db_session.rollback = AsyncMock()

        async def _override_db():
            yield mock_db_session

        mock_redis = AsyncMock()
        mock_redis.get.return_value = None

        async def _override_redis():
            return mock_redis

        app.dependency_overrides[deps.get_db] = _override_db
        app.dependency_overrides[deps.get_redis] = _override_redis

        mock_endpoint = MagicMock()
        mock_endpoint.enabled = True
        mock_endpoint.provider = "openai_compat"
        mock_endpoint.model = "gpt-4"
        mock_endpoint.base_url = "http://fake-llm.local/v1"
        mock_endpoint.api_key_enc = None
        mock_endpoint.max_tokens = 512
        mock_endpoint.model_context_length = 4096
        mock_endpoint.model_capabilities = ""
        mock_endpoint.name = "test-llm"
        mock_endpoint.id = uuid.uuid4()

        mock_log = MagicMock()
        mock_log.id = uuid.uuid4()

        token = create_access_token(user_id=str(uuid.uuid4()), email="operator@test.local", role="operator")

        with (
            patch(
                "fleet_platform.services.llm_svc.get_default_endpoint",
                AsyncMock(return_value=mock_endpoint),
            ),
            patch(
                "fleet_platform.services.llm_svc.get_decrypted_api_key",
                return_value=None,
            ),
            patch(
                "fleet_platform.services.llm_svc.create_query_log",
                AsyncMock(return_value=mock_log),
            ),
            patch(
                "fleet_platform.api.routes.llm.build_fleet_context",
                AsyncMock(return_value=("You are an assistant.", [])),
            ),
            patch(
                "fleet_platform.api.routes.llm._resolve_model",
                AsyncMock(return_value="gpt-4"),
            ),
            patch(
                "fleet_platform.api.routes.llm.call_openai_compat",
                AsyncMock(return_value=("Fleet has 3 online nodes.", 10, 5)),
            ),
            patch(
                "fleet_platform.api.routes.llm.audit",
                new_callable=AsyncMock,
            ) as mock_audit,
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://testserver",
                headers={"Authorization": f"Bearer {token}"},
            ) as client:
                resp = await client.post(
                    "/api/v1/llm/query",
                    json={"prompt": "How many nodes are online?", "intent": "fleet_query"},
                )

        limiter._storage.reset()

        assert resp.status_code == 200, f"Expected 200 from submit_query, got {resp.status_code}: {resp.text}"

        llm_query_calls = [c for c in mock_audit.call_args_list if c.kwargs.get("action") == "llm_query"]
        assert llm_query_calls, (
            "audit() must be called with action='llm_query' on every LLM query (#170). "
            f"Recorded audit calls: {[c.kwargs.get('action') for c in mock_audit.call_args_list]}"
        )

    asyncio.run(_run())
