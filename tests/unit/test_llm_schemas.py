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
        "id", "name", "provider", "base_url", "api_key_encrypted",
        "model", "max_tokens", "is_default", "enabled", "created_at", "updated_at",
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
        "id", "endpoint_id", "user_id", "intent", "prompt", "system_prompt",
        "response", "model_used", "input_tokens", "output_tokens",
        "duration_ms", "error", "created_at",
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
