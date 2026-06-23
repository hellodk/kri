"""#710 Phase A — tool_mode is wired end-to-end (no longer dead schema).

- invalid tool_mode is rejected at the schema boundary (FastAPI → 422)
- normalize_tool_mode falls back safely for legacy/NULL values
- _to_response surfaces the stored tool_mode instead of always returning "json"
"""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from fleet_platform.schemas.llm import (
    VALID_TOOL_MODES,
    LLMEndpointCreate,
    LLMEndpointUpdate,
    normalize_tool_mode,
)


@pytest.mark.parametrize("mode", VALID_TOOL_MODES)
def test_create_accepts_every_valid_tool_mode(mode):
    c = LLMEndpointCreate(name="x", provider="openai_compat", base_url="http://h:1", model="m", tool_mode=mode)
    assert c.tool_mode == mode


@pytest.mark.parametrize("bad", ["", "JSON", "function", "auto", "tools", "yes"])
def test_create_rejects_invalid_tool_mode(bad):
    with pytest.raises(ValidationError):
        LLMEndpointCreate(name="x", provider="openai_compat", base_url="http://h:1", model="m", tool_mode=bad)


def test_update_rejects_invalid_tool_mode():
    with pytest.raises(ValidationError):
        LLMEndpointUpdate(tool_mode="bogus")


def test_update_allows_none_and_valid():
    assert LLMEndpointUpdate().tool_mode is None
    assert LLMEndpointUpdate(tool_mode="none").tool_mode == "none"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("native", "native"),
        ("json", "json"),
        ("anthropic", "anthropic"),
        ("none", "none"),
        (None, "json"),
        ("", "json"),
        ("legacy_value", "json"),
        ("NATIVE", "json"),
    ],
)
def test_normalize_tool_mode(raw, expected):
    assert normalize_tool_mode(raw) == expected


def _fake_endpoint(tool_mode: str):
    return SimpleNamespace(
        id=uuid.uuid4(),
        name="ep",
        provider="openai_compat",
        base_url="http://h:1",
        api_key_encrypted=None,
        model="m",
        max_tokens=4096,
        is_default=False,
        enabled=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        model_context_length=None,
        model_capabilities=None,
        tool_mode=tool_mode,
    )


@pytest.mark.parametrize("mode", ["native", "anthropic", "none"])
def test_to_response_surfaces_stored_tool_mode(mode):
    from fleet_platform.api.routes.llm import _to_response

    resp = _to_response(_fake_endpoint(mode))
    assert resp.tool_mode == mode, "response must reflect the stored tool_mode, not default to json"
