from fleet_platform.services.model_catalog import CATALOG, get_model, get_models

VALID_PROVIDERS = {"mlx", "anthropic", "openai_compat"}


def test_get_models_returns_all_when_no_filter():
    result = get_models()
    assert result is CATALOG
    assert len(result) > 0


def test_get_models_filters_by_mlx():
    result = get_models("mlx")
    assert len(result) > 0
    assert all(m["provider"] == "mlx" for m in result)


def test_get_models_filters_by_anthropic():
    result = get_models("anthropic")
    assert len(result) == 3
    assert all(m["provider"] == "anthropic" for m in result)


def test_get_models_filters_by_openai_compat():
    result = get_models("openai_compat")
    assert len(result) > 0
    assert all(m["provider"] == "openai_compat" for m in result)


def test_get_models_unknown_provider_returns_empty():
    result = get_models("nonexistent")
    assert result == []


def test_get_model_known_id():
    result = get_model("claude-sonnet-4-6")
    assert result is not None
    assert result["id"] == "claude-sonnet-4-6"


def test_get_model_unknown_id():
    result = get_model("does-not-exist")
    assert result is None


def test_get_model_first_mlx_model():
    result = get_model("mlx-community/Llama-3.2-1B-Instruct-4bit")
    assert result is not None
    assert result["provider"] == "mlx"


def test_catalog_entries_have_required_keys():
    required = {"id", "name", "provider", "context_length", "notes"}
    for entry in CATALOG:
        assert required <= entry.keys(), f"Entry missing keys: {entry}"


def test_catalog_provider_values_valid():
    for entry in CATALOG:
        assert entry["provider"] in VALID_PROVIDERS, (
            f"Unexpected provider '{entry['provider']}' for model '{entry['id']}'"
        )


def test_catalog_context_lengths_positive():
    for entry in CATALOG:
        assert entry["context_length"] > 0, f"context_length must be positive for model '{entry['id']}'"


def test_anthropic_models_have_large_context():
    anthropic_models = get_models("anthropic")
    assert len(anthropic_models) > 0
    for m in anthropic_models:
        assert m["context_length"] >= 200000, (
            f"Anthropic model '{m['id']}' has context_length {m['context_length']}, expected >= 200000"
        )
