# LLM Model Selector Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Auto mode, substring search, and health status to the LLM endpoint model dropdown.

**Architecture:** A new `model_health_cache.py` module stores per-model health keyed by `(base_url, provider, model_id)`. Discovery probes populate the cache; the dispatch path in both `llm.py` and `node_actions.py` resolves `"__auto__"` to the lowest-latency healthy model at query time. The frontend replaces the static `<select>` with a `ModelCombobox` component.

**Tech Stack:** Python 3.11 / FastAPI / asyncio / httpx — backend. React 18 / TypeScript / Tailwind — frontend. pytest for tests.

**Spec:** `docs/superpowers/specs/2026-06-09-llm-model-selector-design.md`

---

## Phase 1 — Independent foundations (run Tasks 1 and 2 in parallel)

---

### Task 1: Backend — `model_health_cache.py`

**Files:**
- Create: `fleet_platform/services/model_health_cache.py`
- Create: `tests/unit/test_model_health_cache.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_model_health_cache.py
import time
import pytest
from fleet_platform.services.model_health_cache import (
    set_health, get_healthy_models, evict, is_stale, clear,
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
    # wind the clock forward past TTL
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
```

- [ ] **Step 2: Run tests — confirm they all fail**

```bash
source .venv/bin/activate
pytest tests/unit/test_model_health_cache.py -v
```
Expected: `ModuleNotFoundError` or similar — the module doesn't exist yet.

- [ ] **Step 3: Create `fleet_platform/services/model_health_cache.py`**

```python
"""In-process health cache for discovered LLM models.

Key: (base_url, provider, model_id)
TTL: 5 minutes (300 s)
Thread-safety: single-process asyncio only — no locks needed.
"""
from __future__ import annotations

import time as _time_mod
from typing import TypedDict

_TTL = 300.0


class _Entry(TypedDict):
    healthy: bool
    latency_ms: int | None
    ts: float


_cache: dict[tuple[str, str, str], _Entry] = {}


def _now() -> float:
    return _time_mod.monotonic()


def set_health(
    base_url: str,
    provider: str,
    model_id: str,
    healthy: bool,
    latency_ms: int | None,
) -> None:
    _cache[(base_url, provider, model_id)] = {
        "healthy": healthy,
        "latency_ms": latency_ms,
        "ts": _now(),
    }


def get_healthy_models(base_url: str, provider: str) -> list[dict]:
    """Return fresh healthy models sorted by latency (None sorts last)."""
    now = _now()
    results = [
        {"id": k[2], "latency_ms": v["latency_ms"]}
        for k, v in _cache.items()
        if k[0] == base_url
        and k[1] == provider
        and v["healthy"]
        and (now - v["ts"]) < _TTL
    ]
    return sorted(results, key=lambda m: (m["latency_ms"] is None, m["latency_ms"] or 0))


def evict(base_url: str, provider: str, model_id: str) -> None:
    """Remove a single entry — called when dispatch fails."""
    _cache.pop((base_url, provider, model_id), None)


def is_stale(base_url: str, provider: str) -> bool:
    """True when no fresh entry exists for this endpoint."""
    now = _now()
    return not any(
        k[0] == base_url and k[1] == provider and (now - v["ts"]) < _TTL
        for k, v in _cache.items()
    )


def clear() -> None:
    """Wipe the cache — for tests only."""
    _cache.clear()
```

- [ ] **Step 4: Run tests — confirm they all pass**

```bash
source .venv/bin/activate
pytest tests/unit/test_model_health_cache.py -v
```
Expected: 9 tests pass.

- [ ] **Step 5: Commit**

```bash
git add fleet_platform/services/model_health_cache.py tests/unit/test_model_health_cache.py
git commit -m "feat: add model health cache with TTL and eviction"
```

---

### Task 2: Frontend — `ModelCombobox` component

**Files:**
- Create: `frontend/src/components/ModelCombobox.tsx`

No unit tests for this task (component rendering tested via integration in Task 6). The combobox is a pure UI component with no side effects.

- [ ] **Step 1: Create `frontend/src/components/ModelCombobox.tsx`**

```tsx
import { useState, useRef, useEffect, useCallback } from 'react'
import clsx from 'clsx'

export const AUTO_VALUE = '__auto__'

export interface DiscoveredModel {
  id: string
  name: string
  healthy: boolean
  latency_ms: number | null
}

interface Props {
  models: DiscoveredModel[]
  value: string
  onChange: (value: string) => void
  onRefresh: () => void
  refreshing: boolean
}

export function ModelCombobox({ models, value, onChange, onRefresh, refreshing }: Props) {
  const [search, setSearch] = useState('')
  const [open, setOpen] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  // close on outside click
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [])

  const filtered = models.filter((m) =>
    m.name.toLowerCase().includes(search.toLowerCase())
  )

  const displayValue =
    value === AUTO_VALUE
      ? '⚡ Auto'
      : models.find((m) => m.id === value)?.name ?? value

  function select(id: string) {
    onChange(id)
    setSearch('')
    setOpen(false)
  }

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    },
    []
  )

  const inputClass =
    'w-full px-3 py-2 border border-gray-300 rounded-lg text-sm text-gray-900 ' +
    'focus:outline-none focus:border-brand-600 font-mono'

  return (
    <div ref={containerRef} className="relative">
      {/* label row */}
      <div className="flex items-center justify-between mb-1">
        <label className="text-sm font-medium text-gray-700">
          Model <span className="text-red-500">*</span>
        </label>
        <button
          type="button"
          onClick={onRefresh}
          disabled={refreshing}
          className="text-xs text-brand-600 hover:text-brand-700 disabled:opacity-40 flex items-center gap-1"
          title="Re-probe model health"
        >
          <svg
            width="12"
            height="12"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            className={refreshing ? 'animate-spin' : ''}
          >
            <path d="M23 4v6h-6M1 20v-6h6" />
            <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15" />
          </svg>
          {refreshing ? 'Checking…' : 'Refresh'}
        </button>
      </div>

      {/* trigger input */}
      <div
        className={clsx(
          'w-full px-3 py-2 border rounded-lg text-sm cursor-pointer flex items-center justify-between',
          open ? 'border-brand-600' : 'border-gray-300',
          'bg-white'
        )}
        onClick={() => {
          setOpen((o) => !o)
          setTimeout(() => inputRef.current?.focus(), 0)
        }}
      >
        <span className={clsx('font-mono', value === AUTO_VALUE ? 'text-blue-700 font-semibold' : 'text-gray-900')}>
          {displayValue || <span className="text-gray-400">Select a model…</span>}
        </span>
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#9CA3AF" strokeWidth="2">
          <polyline points="6 9 12 15 18 9" />
        </svg>
      </div>

      {/* dropdown panel */}
      {open && (
        <div className="absolute z-50 w-full mt-1 bg-white border border-gray-200 rounded-lg shadow-lg overflow-hidden">
          {/* search input */}
          <div className="px-3 py-2 border-b border-gray-100">
            <input
              ref={inputRef}
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Filter models…"
              className={inputClass}
              autoComplete="off"
            />
          </div>

          {/* Auto — always pinned, never filtered */}
          <div
            className={clsx(
              'px-3 py-2.5 flex items-center gap-2 cursor-pointer border-b border-blue-100',
              value === AUTO_VALUE ? 'bg-blue-100' : 'bg-blue-50 hover:bg-blue-100'
            )}
            onClick={() => select(AUTO_VALUE)}
          >
            <span className="text-base">⚡</span>
            <div>
              <div className="text-sm font-semibold text-blue-700">Auto</div>
              <div className="text-xs text-blue-500">Smart router picks best model per request</div>
            </div>
          </div>

          {/* model list */}
          <div className="max-h-52 overflow-y-auto">
            {filtered.length === 0 ? (
              <div className="px-3 py-3 text-xs text-gray-400 text-center">No models match</div>
            ) : (
              filtered.map((m) => (
                <div
                  key={m.id}
                  onClick={() => m.healthy && select(m.id)}
                  className={clsx(
                    'px-3 py-2 flex items-center justify-between border-b border-gray-50 last:border-0',
                    m.healthy
                      ? 'cursor-pointer hover:bg-gray-50'
                      : 'opacity-40 cursor-not-allowed',
                    value === m.id && 'bg-gray-100'
                  )}
                >
                  <span className="font-mono text-sm text-gray-900">{m.name}</span>
                  {m.healthy ? (
                    <span className="text-xs text-green-600 font-medium whitespace-nowrap">
                      ● online{m.latency_ms != null ? ` ${m.latency_ms}ms` : ''}
                    </span>
                  ) : (
                    <span className="text-xs text-amber-600 font-medium whitespace-nowrap">⚠ unreachable</span>
                  )}
                </div>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 2: Build the frontend to confirm no type errors**

```bash
cd frontend && npm run build 2>&1 | tail -20
```
Expected: build completes with 0 TypeScript errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/ModelCombobox.tsx
git commit -m "feat: add ModelCombobox with Auto mode, health badges, substring search"
```

---

## Phase 2 — Wired features (run Tasks 3, 4, 5, 6 in parallel after Phase 1)

---

### Task 3: Backend — Discovery with health probing

**Depends on:** Task 1 (model_health_cache)

**Files:**
- Modify: `fleet_platform/services/model_discovery.py`
- Modify: `fleet_platform/schemas/llm.py` (add `DiscoveredModel`)
- Modify: `fleet_platform/api/routes/llm.py:46-53` (update discover handler)
- Create: `tests/unit/test_model_discovery_health.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_model_discovery_health.py
import pytest
import respx
import httpx
from fleet_platform.services.model_discovery import discover_models_with_health
from fleet_platform.services.model_health_cache import clear, get_healthy_models

@pytest.fixture(autouse=True)
def reset_cache():
    clear()
    yield
    clear()


@pytest.mark.anyio
@respx.mock
async def test_ollama_all_healthy_no_latency():
    respx.get("http://ollama:11434/api/tags").mock(
        return_value=httpx.Response(200, json={
            "models": [{"name": "llama3.2"}, {"name": "codestral"}]
        })
    )
    result = await discover_models_with_health("http://ollama:11434", "ollama", api_key=None)
    assert len(result) == 2
    assert all(m["healthy"] is True for m in result)
    assert all(m["latency_ms"] is None for m in result)


@pytest.mark.anyio
@respx.mock
async def test_ollama_populates_cache():
    respx.get("http://ollama:11434/api/tags").mock(
        return_value=httpx.Response(200, json={"models": [{"name": "llama3.2"}]})
    )
    await discover_models_with_health("http://ollama:11434", "ollama", api_key=None)
    healthy = get_healthy_models("http://ollama:11434", "ollama")
    assert len(healthy) == 1
    assert healthy[0]["id"] == "llama3.2"


@pytest.mark.anyio
@respx.mock
async def test_vllm_probes_and_marks_healthy():
    respx.get("http://vllm:8000/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "mistral"}]})
    )
    respx.post("http://vllm:8000/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={
            "choices": [{"message": {"content": "hi"}}]
        })
    )
    result = await discover_models_with_health("http://vllm:8000", "vllm", api_key=None)
    assert result[0]["healthy"] is True
    assert result[0]["latency_ms"] is not None


@pytest.mark.anyio
@respx.mock
async def test_vllm_marks_unhealthy_on_probe_failure():
    respx.get("http://vllm:8000/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "broken"}]})
    )
    respx.post("http://vllm:8000/v1/chat/completions").mock(
        return_value=httpx.Response(503)
    )
    result = await discover_models_with_health("http://vllm:8000", "vllm", api_key=None)
    assert result[0]["healthy"] is False
    assert result[0]["latency_ms"] is None


@pytest.mark.anyio
@respx.mock
async def test_empty_on_unreachable_endpoint():
    respx.get("http://gone:11434/api/tags").mock(side_effect=httpx.ConnectError("refused"))
    result = await discover_models_with_health("http://gone:11434", "ollama", api_key=None)
    assert result == []
```

- [ ] **Step 2: Run tests — confirm they fail**

```bash
source .venv/bin/activate
pytest tests/unit/test_model_discovery_health.py -v
```
Expected: `ImportError` — `discover_models_with_health` doesn't exist yet.

- [ ] **Step 3: Add `DiscoveredModel` schema to `fleet_platform/schemas/llm.py`**

Add after the existing imports (after line 8):

```python
class DiscoveredModel(BaseModel):
    id: str
    name: str
    healthy: bool
    latency_ms: int | None = None
```

- [ ] **Step 4: Add `discover_models_with_health` to `fleet_platform/services/model_discovery.py`**

Replace the entire file contents with:

```python
"""Discover available models from a live LLM provider endpoint."""
from __future__ import annotations

import asyncio
import logging
import time

import httpx

from fleet_platform.services.llm_caller import normalize_openai_base_url
from fleet_platform.services import model_health_cache as _cache

_log = logging.getLogger(__name__)
_TIMEOUT = 8.0
_PROBE_TIMEOUT = 5.0


async def discover_models(url: str, provider: str) -> list[dict]:
    """Legacy: return model list without health info. Used by get_models() helper."""
    results = await discover_models_with_health(url, provider, api_key=None)
    return [{"id": m["id"], "name": m["name"], "context_length": 0, "capabilities": []} for m in results]


async def _probe_model(base_url: str, model_id: str, api_key: str | None) -> tuple[bool, int | None]:
    """Send a 1-token chat request. Returns (healthy, latency_ms)."""
    t0 = time.monotonic()
    try:
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT) as client:
            resp = await client.post(
                f"{base_url}/v1/chat/completions",
                json={
                    "model": model_id,
                    "messages": [{"role": "user", "content": "hi"}],
                    "max_tokens": 1,
                },
                headers=headers,
            )
            resp.raise_for_status()
        return True, int((time.monotonic() - t0) * 1000)
    except Exception:
        return False, None


async def discover_models_with_health(
    url: str, provider: str, api_key: str | None
) -> list[dict]:
    """Query provider for models and assess health. Populates the health cache.

    Returns list of {id, name, healthy, latency_ms}.
    Returns [] on any error (never raises).
    """
    base = normalize_openai_base_url(url)
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            if provider == "ollama":
                resp = await client.get(f"{base}/api/tags")
                resp.raise_for_status()
                data = resp.json()
                models = [
                    {"id": m["name"], "name": m["name"], "healthy": True, "latency_ms": None}
                    for m in data.get("models", [])
                ]
                for m in models:
                    _cache.set_health(url, provider, m["id"], healthy=True, latency_ms=None)
                return models
            else:
                resp = await client.get(f"{base}/v1/models")
                resp.raise_for_status()
                data = resp.json()
                model_ids = [m["id"] for m in data.get("data", [])]
                model_names = {m["id"]: m.get("name", m["id"]) for m in data.get("data", [])}

        # probe all non-Ollama models concurrently
        probes = await asyncio.gather(
            *[_probe_model(base, mid, api_key) for mid in model_ids],
            return_exceptions=False,
        )

        results = []
        for mid, (healthy, latency_ms) in zip(model_ids, probes):
            _cache.set_health(url, provider, mid, healthy=healthy, latency_ms=latency_ms)
            results.append({
                "id": mid,
                "name": model_names[mid],
                "healthy": healthy,
                "latency_ms": latency_ms,
            })
        return results

    except Exception as exc:
        _log.debug("model_discovery: could not reach %s (%s): %s", url, provider, exc)
        return []
```

- [ ] **Step 5: Update `fleet_platform/api/routes/llm.py` — discover handler (lines 41–53)**

Replace the `discover_endpoint_models` handler:

```python
class DiscoverModelsRequest(BaseModel):
    url: str
    provider: str


@router.post("/discover-models")
async def discover_endpoint_models(
    req: DiscoverModelsRequest,
    _: dict = Depends(require_role("operator", "admin")),
):
    """Query a provider endpoint, probe health, and return available models."""
    from fleet_platform.services.model_discovery import discover_models_with_health
    from fleet_platform.schemas.llm import DiscoveredModel
    models = await discover_models_with_health(req.url, req.provider, api_key=None)
    return {"models": [DiscoveredModel(**m) for m in models]}
```

Also add the import at the top of the file (replace the existing `from fleet_platform.services.model_discovery import discover_models` import):

```python
from fleet_platform.services.model_discovery import discover_models, discover_models_with_health
```

- [ ] **Step 6: Run tests — confirm they pass**

```bash
source .venv/bin/activate
pytest tests/unit/test_model_discovery_health.py -v
```
Expected: 5 tests pass.

- [ ] **Step 7: Run ruff on changed files**

```bash
source .venv/bin/activate
ruff check fleet_platform/services/model_discovery.py fleet_platform/schemas/llm.py fleet_platform/api/routes/llm.py
ruff format --check fleet_platform/services/model_discovery.py fleet_platform/schemas/llm.py fleet_platform/api/routes/llm.py
```
Expected: 0 findings. Fix any issues before committing.

- [ ] **Step 8: Commit**

```bash
git add fleet_platform/services/model_discovery.py fleet_platform/schemas/llm.py fleet_platform/api/routes/llm.py tests/unit/test_model_discovery_health.py
git commit -m "feat: probe model health on discovery, populate cache, return healthy+latency"
```

---

### Task 4: Backend — Auto routing in `llm.py`

**Depends on:** Task 1 (model_health_cache)

**Files:**
- Modify: `fleet_platform/api/routes/llm.py:254-328`
- Create: `tests/unit/test_auto_model_routing_llm.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_auto_model_routing_llm.py
import pytest
from fleet_platform.services import model_health_cache as cache
from fleet_platform.services.model_health_cache import clear


@pytest.fixture(autouse=True)
def reset():
    clear()
    yield
    clear()


def test_resolve_auto_picks_lowest_latency():
    cache.set_health("http://x", "vllm", "slow", healthy=True, latency_ms=200)
    cache.set_health("http://x", "vllm", "fast", healthy=True, latency_ms=15)
    healthy = cache.get_healthy_models("http://x", "vllm")
    assert healthy[0]["id"] == "fast"


def test_resolve_auto_ollama_null_latency_sorts_last():
    cache.set_health("http://x", "vllm", "probed", healthy=True, latency_ms=50)
    cache.set_health("http://x", "vllm", "noprobe", healthy=True, latency_ms=None)
    healthy = cache.get_healthy_models("http://x", "vllm")
    assert healthy[0]["id"] == "probed"
    assert healthy[1]["id"] == "noprobe"


def test_resolve_auto_all_unhealthy_returns_empty():
    cache.set_health("http://x", "vllm", "m1", healthy=False, latency_ms=None)
    assert cache.get_healthy_models("http://x", "vllm") == []


def test_evict_and_retry():
    cache.set_health("http://x", "vllm", "m1", healthy=True, latency_ms=10)
    cache.set_health("http://x", "vllm", "m2", healthy=True, latency_ms=20)
    # simulate dispatch failure on m1
    cache.evict("http://x", "vllm", "m1")
    healthy = cache.get_healthy_models("http://x", "vllm")
    assert len(healthy) == 1
    assert healthy[0]["id"] == "m2"
```

- [ ] **Step 2: Run tests — confirm they pass immediately**

These tests only exercise the cache module (already built). They should all pass:

```bash
source .venv/bin/activate
pytest tests/unit/test_auto_model_routing_llm.py -v
```
Expected: 4 tests pass (they're testing cache logic).

- [ ] **Step 3: Add `_resolve_model` helper to `fleet_platform/api/routes/llm.py`**

Add this function after the imports and before `router = APIRouter(...)` (or at the top of the route file after imports):

```python
async def _resolve_model(endpoint, db=None) -> str:
    """Resolve '__auto__' to a concrete model id.

    For a non-auto endpoint, returns endpoint.model unchanged.
    For __auto__, picks the lowest-latency healthy model from the cache,
    re-probing if the cache is stale. Raises HTTP 503 if no healthy model found.
    """
    from fleet_platform.services import model_health_cache as hc
    from fleet_platform.services.model_discovery import discover_models_with_health
    from fleet_platform.services.llm_svc import get_decrypted_api_key

    if endpoint.model != "__auto__":
        return endpoint.model

    url = endpoint.base_url or ""
    provider = endpoint.provider

    if hc.is_stale(url, provider):
        api_key = get_decrypted_api_key(endpoint)
        await discover_models_with_health(url, provider, api_key=api_key)

    healthy = hc.get_healthy_models(url, provider)
    if not healthy:
        raise HTTPException(
            status_code=503,
            detail=f"No healthy models available on endpoint '{endpoint.name}'. "
                   "Refresh model status or check the endpoint URL.",
        )
    return healthy[0]["id"]
```

- [ ] **Step 4: Wire `_resolve_model` into the query dispatch in `fleet_platform/api/routes/llm.py`**

In the `query_llm` handler, after the existing intent resolution block (after line 238), add:

```python
    chosen_model = await _resolve_model(endpoint)
```

Then replace every occurrence of `endpoint.model` in the dispatch and response with `chosen_model`:

```python
    # anthropic branch (was endpoint.model at line 264):
    content, input_tokens, output_tokens = await call_anthropic(
        api_key=api_key or "",
        model=chosen_model,          # ← changed
        ...
    )
    # openai_compat branch (was endpoint.model at line 274):
    content, input_tokens, output_tokens = await call_openai_compat(
        ...
        model=chosen_model,          # ← changed
        ...
    )
    # on LLMCallError (add eviction before re-raise):
    except (LLMCallError, Exception) as exc:
        if endpoint.model == "__auto__":
            from fleet_platform.services import model_health_cache as hc
            hc.evict(endpoint.base_url or "", endpoint.provider, chosen_model)
        error = str(exc)

    # model_used in create_query_log (was endpoint.model at line 295):
    model_used=chosen_model,         # ← changed

    # audit new_value (was endpoint.model at line 311):
    "model": chosen_model,           # ← changed

    # LLMQueryResponse (was endpoint.model at line 323):
    model_used=chosen_model,         # ← changed
```

- [ ] **Step 5: Run ruff + existing unit tests**

```bash
source .venv/bin/activate
ruff check fleet_platform/api/routes/llm.py
ruff format --check fleet_platform/api/routes/llm.py
pytest tests/unit/test_auto_model_routing_llm.py -v
```
Expected: 0 ruff findings, 4 tests pass.

- [ ] **Step 6: Commit**

```bash
git add fleet_platform/api/routes/llm.py tests/unit/test_auto_model_routing_llm.py
git commit -m "feat: resolve __auto__ model sentinel at query dispatch in llm.py"
```

---

### Task 5: Backend — Auto routing in `node_actions.py`

**Depends on:** Task 1 (model_health_cache)

**Files:**
- Modify: `fleet_platform/api/routes/node_actions.py:358-394`

No new tests — the eviction/cache logic is covered by Task 4's tests. This task is a mechanical mirror of Task 4 for the node-actions dispatch path.

- [ ] **Step 1: Add `_resolve_model` import and wire it in `node_actions.py`**

Add a local `_resolve_model` helper at the top of the function that uses the LLM endpoint (around line 358, inside the `generate_node_recommendation` handler), right after `api_key = get_decrypted_api_key(endpoint)`:

```python
    # Resolve __auto__ sentinel
    async def _resolve_model_local(ep) -> str:
        from fleet_platform.services import model_health_cache as hc
        from fleet_platform.services.model_discovery import discover_models_with_health
        if ep.model != "__auto__":
            return ep.model
        url = ep.base_url or ""
        if hc.is_stale(url, ep.provider):
            await discover_models_with_health(url, ep.provider, api_key=get_decrypted_api_key(ep))
        healthy = hc.get_healthy_models(url, ep.provider)
        if not healthy:
            raise HTTPException(
                status_code=503,
                detail=f"No healthy models on endpoint '{ep.name}'. Check URL or refresh.",
            )
        return healthy[0]["id"]

    chosen_model = await _resolve_model_local(endpoint)
```

Replace `endpoint.model` at lines 368, 377, 391 with `chosen_model`:

```python
    try:
        if endpoint.provider == "anthropic":
            content, input_tokens, output_tokens = await call_anthropic(
                api_key=api_key or "",
                model=chosen_model,                         # ← line 368
                max_tokens=min(endpoint.max_tokens, 512),
                system_prompt=system_prompt,
                user_prompt=node_context,
            )
        else:
            content, input_tokens, output_tokens = await call_openai_compat(
                base_url=endpoint.base_url,
                api_key=api_key,
                model=chosen_model,                         # ← line 377
                max_tokens=min(endpoint.max_tokens, 512),
                system_prompt=system_prompt,
                user_prompt=node_context,
                model_context_length=endpoint.model_context_length,
                model_capabilities=model_caps,
            )
    except LLMCallError as exc:
        if endpoint.model == "__auto__":
            from fleet_platform.services import model_health_cache as hc
            hc.evict(endpoint.base_url or "", endpoint.provider, chosen_model)
        raise HTTPException(status_code=502, detail=f"LLM call failed: {exc}") from exc

    return {
        "node_id": str(node_id),
        "node_name": node_name,
        "recommendation": content,
        "model_used": chosen_model,                         # ← line 391
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
    }
```

- [ ] **Step 2: Run ruff**

```bash
source .venv/bin/activate
ruff check fleet_platform/api/routes/node_actions.py
ruff format --check fleet_platform/api/routes/node_actions.py
```
Expected: 0 findings.

- [ ] **Step 3: Commit**

```bash
git add fleet_platform/api/routes/node_actions.py
git commit -m "feat: resolve __auto__ model sentinel in node_actions dispatch path"
```

---

### Task 6: Frontend — Wire ModelCombobox into the form + API types + SettingsPage display

**Depends on:** Task 2 (ModelCombobox component)

**Files:**
- Modify: `frontend/src/api/llm.ts`
- Modify: `frontend/src/components/LLMEndpointForm.tsx`
- Modify: `frontend/src/pages/SettingsPage.tsx:2160`

- [ ] **Step 1: Update `frontend/src/api/llm.ts` — `discoverModels` return type**

Replace lines 84–85:

```ts
  discoverModels: (url: string, provider: string) =>
    api.post<{ models: Array<{ id: string; name: string; healthy: boolean; latency_ms: number | null }> }>(
      '/api/v1/llm/discover-models',
      { url, provider }
    ),
```

- [ ] **Step 2: Update `frontend/src/components/LLMEndpointForm.tsx`**

**2a.** Add import at top (after existing imports):

```tsx
import { ModelCombobox, AUTO_VALUE, type DiscoveredModel } from './ModelCombobox'
```

**2b.** Change `discoveredModels` state type (line 35):

```tsx
const [discoveredModels, setDiscoveredModels] = useState<DiscoveredModel[]>([])
```

**2c.** Change default selection on discovery (lines 93–95) — replace:

```tsx
        if (res.models.length > 0 && !model) {
          setModel(res.models[0].id)
        }
```
with:
```tsx
        if (res.models.length > 0 && !model) {
          setModel(AUTO_VALUE)
        }
```

**2d.** Add a `handleRefresh` callback above the return statement:

```tsx
  async function handleRefresh() {
    if (!baseUrl.trim() || provider === 'anthropic') return
    setDiscovering(true)
    setDiscoveryError(null)
    try {
      const res = await llmApi.discoverModels(baseUrl.trim(), provider)
      setDiscoveredModels(res.models)
    } catch {
      setDiscoveryError('Could not reach endpoint')
      setDiscoveredModels([])
    } finally {
      setDiscovering(false)
    }
  }
```

**2e.** Replace the Model field block (lines 226–268) with:

```tsx
          {/* Model */}
          <div>
            {discoveredModels.length > 0 ? (
              <ModelCombobox
                models={discoveredModels}
                value={model}
                onChange={setModel}
                onRefresh={handleRefresh}
                refreshing={discovering}
              />
            ) : (
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1 flex items-center gap-2">
                  Model <span className="text-red-500">*</span>
                  {discovering && (
                    <span className="text-xs text-brand-500 font-normal">Discovering…</span>
                  )}
                  {discoveryError && (
                    <span className="text-xs text-amber-600 font-normal">&#9888; {discoveryError}</span>
                  )}
                </label>
                <input
                  type="text"
                  value={model}
                  onChange={(e) => setModel(e.target.value)}
                  placeholder={
                    provider === 'anthropic' ? 'claude-sonnet-4-6' :
                    provider === 'ollama'    ? 'llama3.2' :
                    'model-id'
                  }
                  className={inputClass + ' font-mono'}
                  required
                />
              </div>
            )}
          </div>
```

- [ ] **Step 3: Update `frontend/src/pages/SettingsPage.tsx` — model display (line 2160)**

Replace:
```tsx
                        <span className="font-mono text-gray-700 text-xs">{ep.model}</span>
```
with:
```tsx
                        {ep.model === '__auto__' ? (
                          <span className="text-blue-700 text-xs font-semibold">⚡ Auto</span>
                        ) : (
                          <span className="font-mono text-gray-700 text-xs">{ep.model}</span>
                        )}
```

- [ ] **Step 4: Build the frontend**

```bash
cd frontend && npm run build 2>&1 | tail -20
```
Expected: 0 TypeScript errors.

- [ ] **Step 5: Run eslint on changed files**

```bash
cd frontend && npx eslint src/api/llm.ts src/components/LLMEndpointForm.tsx src/components/ModelCombobox.tsx src/pages/SettingsPage.tsx
```
Expected: 0 errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api/llm.ts frontend/src/components/LLMEndpointForm.tsx frontend/src/pages/SettingsPage.tsx
git commit -m "feat: wire ModelCombobox into LLM endpoint form, show Auto in settings list"
```

---

## Verification

After all tasks complete, run the full backend unit suite:

```bash
source .venv/bin/activate
pytest tests/unit/ -q
```
Expected: 0 failures, no regressions.

And the frontend build one final time:

```bash
cd frontend && npm run build 2>&1 | tail -5
```
Expected: 0 errors.
