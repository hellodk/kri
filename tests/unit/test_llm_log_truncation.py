"""Unit tests for #137 — LLM query log system_prompt truncation."""
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_system_prompt_truncated_in_log():
    """system_prompt longer than 500 chars must be truncated before storage."""
    from fleet_platform.services import llm_svc

    db = AsyncMock()
    db.add = MagicMock()

    long_prompt = "x" * 1000
    await llm_svc.create_query_log(
        db,
        endpoint_id=None,
        user_id="user1",
        intent="test",
        prompt="short prompt",
        system_prompt=long_prompt,
        response=None,
        model_used="test",
        input_tokens=0,
        output_tokens=0,
        duration_ms=100,
        error=None,
    )

    db.add.assert_called_once()
    logged_obj = db.add.call_args[0][0]
    assert len(logged_obj.system_prompt) < len(long_prompt), (
        "system_prompt must be truncated before storage"
    )
    assert "[truncated]" in logged_obj.system_prompt


@pytest.mark.asyncio
async def test_short_system_prompt_not_truncated():
    """Short system_prompts must be stored as-is."""
    from fleet_platform.services import llm_svc

    db = AsyncMock()
    db.add = MagicMock()

    short_prompt = "This is a short prompt."
    await llm_svc.create_query_log(
        db,
        endpoint_id=None,
        user_id="user1",
        intent="test",
        prompt="short",
        system_prompt=short_prompt,
        response=None,
        model_used="test",
        input_tokens=0,
        output_tokens=0,
        duration_ms=100,
        error=None,
    )

    logged_obj = db.add.call_args[0][0]
    assert logged_obj.system_prompt == short_prompt


@pytest.mark.asyncio
async def test_user_prompt_truncated_in_log():
    """User prompt longer than 2000 chars must also be truncated."""
    from fleet_platform.services import llm_svc

    db = AsyncMock()
    db.add = MagicMock()

    long_user_prompt = "a" * 5000
    await llm_svc.create_query_log(
        db,
        endpoint_id=None,
        user_id="user1",
        intent="test",
        prompt=long_user_prompt,
        system_prompt="short",
        response=None,
        model_used="test",
        input_tokens=0,
        output_tokens=0,
        duration_ms=100,
        error=None,
    )

    logged_obj = db.add.call_args[0][0]
    assert len(logged_obj.prompt) < len(long_user_prompt)
    assert "[truncated]" in logged_obj.prompt
