import time

import pytest

from fleet_platform.services.model_health_cache import (
    clear,
    evict,
    get_healthy_models,
    is_stale,
    set_health,
)


@pytest.fixture(autouse=True)
def reset():
    clear()
    yield
    clear()


def test_set_and_get_healthy():
    set_health("http://x", "ollama", "llama3.2", healthy=True, latency_ms=None)
    models = get_healthy_models("http://x", "ollama")
    assert len(models) == 1
    assert models[0]["id"] == "llama3.2"
    assert models[0]["latency_ms"] is None


def test_unhealthy_not_returned():
    set_health("http://x", "ollama", "llama3.2", healthy=False, latency_ms=None)
    assert get_healthy_models("http://x", "ollama") == []


def test_evict_removes_entry():
    set_health("http://x", "ollama", "llama3.2", healthy=True, latency_ms=28)
    evict("http://x", "ollama", "llama3.2")
    assert get_healthy_models("http://x", "ollama") == []


def test_evict_missing_key_is_noop():
    evict("http://x", "ollama", "nonexistent")  # must not raise


def test_is_stale_when_empty():
    assert is_stale("http://x", "ollama") is True


def test_is_stale_false_when_fresh():
    set_health("http://x", "ollama", "llama3.2", healthy=True, latency_ms=None)
    assert is_stale("http://x", "ollama") is False


def test_is_stale_true_after_ttl(monkeypatch):
    import fleet_platform.services.model_health_cache as mod

    set_health("http://x", "ollama", "llama3.2", healthy=True, latency_ms=None)
    monkeypatch.setattr(mod, "_now", lambda: time.monotonic() + 400)
    assert is_stale("http://x", "ollama") is True


def test_get_healthy_excludes_expired(monkeypatch):
    import fleet_platform.services.model_health_cache as mod

    set_health("http://x", "ollama", "llama3.2", healthy=True, latency_ms=None)
    monkeypatch.setattr(mod, "_now", lambda: time.monotonic() + 400)
    assert get_healthy_models("http://x", "ollama") == []


def test_get_healthy_sorted_by_latency():
    set_health("http://x", "vllm", "fast", healthy=True, latency_ms=10)
    set_health("http://x", "vllm", "slow", healthy=True, latency_ms=200)
    set_health("http://x", "vllm", "nolatency", healthy=True, latency_ms=None)
    models = get_healthy_models("http://x", "vllm")
    ids = [m["id"] for m in models]
    assert ids == ["fast", "slow", "nolatency"]


def test_different_urls_dont_mix():
    set_health("http://a", "ollama", "m1", healthy=True, latency_ms=None)
    set_health("http://b", "ollama", "m2", healthy=True, latency_ms=None)
    assert [m["id"] for m in get_healthy_models("http://a", "ollama")] == ["m1"]
    assert [m["id"] for m in get_healthy_models("http://b", "ollama")] == ["m2"]
