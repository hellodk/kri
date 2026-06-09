"""Unit tests for LLMEndpoint and LLMQueryLog SQLAlchemy models."""

import uuid

from sqlalchemy import inspect as sa_inspect


def test_llm_endpoint_tablename():
    from fleet_platform.models.llm_endpoint import LLMEndpoint

    assert LLMEndpoint.__tablename__ == "llm_endpoints"


def test_llm_endpoint_has_expected_columns():
    from fleet_platform.models.llm_endpoint import LLMEndpoint

    mapper = sa_inspect(LLMEndpoint)
    col_names = {c.key for c in mapper.columns}
    expected = {
        "id",
        "name",
        "provider",
        "base_url",
        "api_key_encrypted",
        "model",
        "max_tokens",
        "is_default",
        "enabled",
        "created_at",
        "updated_at",
    }
    assert expected.issubset(col_names), f"Missing columns: {expected - col_names}"


def test_llm_endpoint_column_defaults():
    from fleet_platform.models.llm_endpoint import LLMEndpoint

    mapper = sa_inspect(LLMEndpoint)
    assert mapper.c.max_tokens.default.arg == 4096
    assert mapper.c.is_default.default.arg is False
    assert mapper.c.enabled.default.arg is True


def test_llm_endpoint_api_key_encrypted_is_nullable():
    from fleet_platform.models.llm_endpoint import LLMEndpoint

    mapper = sa_inspect(LLMEndpoint)
    assert mapper.c.api_key_encrypted.nullable is True


def test_llm_endpoint_unique_uuid_default():
    from fleet_platform.models.llm_endpoint import LLMEndpoint

    e1 = LLMEndpoint(name="a", provider="openai_compat", base_url="http://x", model="m")
    e2 = LLMEndpoint(name="b", provider="openai_compat", base_url="http://y", model="m")
    assert e1.id != e2.id
    assert isinstance(e1.id, uuid.UUID)


def test_llm_endpoint_has_indexes():
    from fleet_platform.models.llm_endpoint import LLMEndpoint

    index_names = {idx.name for idx in LLMEndpoint.__table__.indexes}
    assert "idx_llm_endpoints_is_default" in index_names
    assert "idx_llm_endpoints_enabled" in index_names


def test_llm_query_log_tablename():
    from fleet_platform.models.llm_query_log import LLMQueryLog

    assert LLMQueryLog.__tablename__ == "llm_query_log"


def test_llm_query_log_has_expected_columns():
    from fleet_platform.models.llm_query_log import LLMQueryLog

    mapper = sa_inspect(LLMQueryLog)
    col_names = {c.key for c in mapper.columns}
    expected = {
        "id",
        "endpoint_id",
        "user_id",
        "intent",
        "prompt",
        "system_prompt",
        "response",
        "model_used",
        "input_tokens",
        "output_tokens",
        "duration_ms",
        "error",
        "created_at",
    }
    assert expected.issubset(col_names), f"Missing columns: {expected - col_names}"


def test_llm_query_log_endpoint_id_nullable():
    from fleet_platform.models.llm_query_log import LLMQueryLog

    mapper = sa_inspect(LLMQueryLog)
    assert mapper.c.endpoint_id.nullable is True


def test_llm_query_log_endpoint_id_has_fk_to_llm_endpoints():
    from fleet_platform.models.llm_query_log import LLMQueryLog

    mapper = sa_inspect(LLMQueryLog)
    fks = mapper.c.endpoint_id.foreign_keys
    assert len(fks) == 1
    fk = next(iter(fks))
    assert "llm_endpoints" in fk.target_fullname


def test_llm_query_log_has_indexes():
    from fleet_platform.models.llm_query_log import LLMQueryLog

    index_names = {idx.name for idx in LLMQueryLog.__table__.indexes}
    assert "idx_llm_query_log_user_id" in index_names
    assert "idx_llm_query_log_endpoint_id" in index_names


def test_llm_models_exported_from_package():
    from fleet_platform.models import LLMEndpoint, LLMQueryLog

    assert LLMEndpoint.__tablename__ == "llm_endpoints"
    assert LLMQueryLog.__tablename__ == "llm_query_log"


# ── Pydantic schema tests ──────────────────────────────────────────────────


def test_llm_endpoint_create_rejects_unknown_provider():
    import pytest
    from pydantic import ValidationError

    from fleet_platform.schemas.llm import LLMEndpointCreate

    with pytest.raises(ValidationError):
        LLMEndpointCreate(
            name="bad",
            provider="gemini",  # not in Literal["openai_compat","anthropic"]
            base_url="http://example.com",
            model="gemini-pro",
        )


def test_llm_endpoint_create_accepts_valid_providers():
    from fleet_platform.schemas.llm import LLMEndpointCreate

    for provider in ("openai_compat", "anthropic"):
        obj = LLMEndpointCreate(name="x", provider=provider, base_url="http://x", model="m")
        assert obj.provider == provider


def test_llm_endpoint_response_has_no_api_key_field():
    import datetime
    import uuid

    from fleet_platform.schemas.llm import LLMEndpointResponse

    r = LLMEndpointResponse(
        id=uuid.uuid4(),
        name="test",
        provider="openai_compat",
        base_url="http://localhost:11434/v1",
        has_api_key=True,
        model="llama3.2",
        max_tokens=4096,
        is_default=True,
        enabled=True,
        created_at=datetime.datetime.now(),
        updated_at=datetime.datetime.now(),
    )
    assert not hasattr(r, "api_key")
    assert not hasattr(r, "api_key_encrypted")
    assert r.has_api_key is True


def test_llm_query_request_valid_intents():
    import pytest
    from pydantic import ValidationError

    from fleet_platform.schemas.llm import LLMQueryRequest

    for intent in ("salt_state", "ansible_playbook", "fleet_command", "explain", "fleet_query"):
        req = LLMQueryRequest(prompt="do something", intent=intent)
        assert req.intent == intent
    with pytest.raises(ValidationError):
        LLMQueryRequest(prompt="do something", intent="magic_wand")


def test_llm_query_request_prompt_min_length():
    import pytest
    from pydantic import ValidationError

    from fleet_platform.schemas.llm import LLMQueryRequest

    with pytest.raises(ValidationError):
        LLMQueryRequest(prompt="", intent="explain")


def test_llm_endpoint_update_all_fields_optional():
    from fleet_platform.schemas.llm import LLMEndpointUpdate

    # Should construct with no fields — all optional
    obj = LLMEndpointUpdate()
    assert obj.name is None
    assert obj.base_url is None
    assert obj.model is None


def test_llm_endpoint_update_accepts_provider():
    """Provider must be editable on update, not silently dropped (#277)."""
    from fleet_platform.schemas.llm import LLMEndpointUpdate

    obj = LLMEndpointUpdate(provider="openai_compat")
    assert obj.provider == "openai_compat"
    # Omitted -> None (so update_endpoint leaves it unchanged)
    assert LLMEndpointUpdate().provider is None


def test_llm_endpoint_update_rejects_unknown_provider():
    import pytest
    from pydantic import ValidationError

    from fleet_platform.schemas.llm import LLMEndpointUpdate

    with pytest.raises(ValidationError):
        LLMEndpointUpdate(provider="gemini")


def test_llm_endpoint_response_model_validate_with_api_key():
    import datetime

    from fleet_platform.models.llm_endpoint import LLMEndpoint
    from fleet_platform.schemas.llm import LLMEndpointResponse

    now = datetime.datetime.now(datetime.timezone.utc)
    endpoint = LLMEndpoint(
        name="ollama",
        provider="openai_compat",
        base_url="http://localhost:11434/v1",
        model="llama3.2",
        api_key_encrypted="encrypted-ciphertext",
        max_tokens=4096,
        is_default=False,
        enabled=True,
        tool_mode="json",
        created_at=now,
        updated_at=now,
    )
    response = LLMEndpointResponse.model_validate(endpoint)
    assert response.has_api_key is True
    assert not hasattr(response, "api_key_encrypted")


def test_llm_endpoint_response_model_validate_without_api_key():
    import datetime

    from fleet_platform.models.llm_endpoint import LLMEndpoint
    from fleet_platform.schemas.llm import LLMEndpointResponse

    now = datetime.datetime.now(datetime.timezone.utc)
    endpoint = LLMEndpoint(
        name="local-ollama",
        provider="openai_compat",
        base_url="http://localhost:11434/v1",
        model="llama3.2",
        api_key_encrypted=None,
        max_tokens=4096,
        is_default=False,
        enabled=True,
        tool_mode="json",
        created_at=now,
        updated_at=now,
    )
    response = LLMEndpointResponse.model_validate(endpoint)
    assert response.has_api_key is False


def test_max_tokens_schema_cap():
    """Schema and frontend agree on max_tokens ceiling (#275)."""
    import pytest
    from pydantic import ValidationError

    from fleet_platform.schemas.llm import LLMEndpointCreate

    # At the cap — valid
    ep = LLMEndpointCreate(name="x", provider="openai_compat", base_url="http://x", model="m", max_tokens=200000)
    assert ep.max_tokens == 200000

    # Over the cap — invalid
    with pytest.raises(ValidationError):
        LLMEndpointCreate(name="x", provider="openai_compat", base_url="http://x", model="m", max_tokens=200001)
