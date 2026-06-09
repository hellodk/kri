# LLM Endpoint Model Selector — Design Spec

**Date:** 2026-06-09
**Status:** Revised after principal review (v2)

---

## Problem

LLM endpoints (Ollama, vLLM, llama.cpp) often serve multiple models. The current form forces the
user to type a model name manually or pick from a plain `<select>` with no search. There is no way
to:

1. Let a router pick a working model automatically.
2. Search a large model list (30–50 models) quickly.
3. Know which models are actually reachable before saving.

---

## Goals

1. Add **Auto mode** — a sentinel model choice where the backend router picks the lowest-latency
   healthy model at query time.
2. Add **substring search** in the model dropdown when models have been discovered.
3. Add **health status** in the dropdown — grey out models that failed the discovery probe before
   the user selects one.

---

## Out of Scope

- Intent-aware model scoring (needs a per-model capability store that does not exist — separate
  ticket).
- Persistent health polling (background poller every N seconds — explicitly rejected due to
  performance cost).
- Changes to provider list or API key handling.

---

## Key decisions (from review)

| Decision | Rationale |
|----------|-----------|
| Auto = lowest-latency healthy model, not intent-scored | Per-model capability data does not exist in the schema. Scoring would degrade silently to "fastest model" regardless of intent. Ship the honest behaviour. |
| Health check = discovery list membership, not inference probe | `model_discovery.py` already hits `/api/tags` (Ollama) and `/v1/models` (vLLM/others) — if the model is in the list, the endpoint is serving it. Concurrent inference probes against a 50-model Ollama host would thrash VRAM and generate false-unhealthy results. |
| Latency = single lightweight inference probe per model for non-Ollama only | vLLM/llamacpp load at startup — a 1-token probe is safe and gives real latency data. Ollama lazy-loads from disk; `latency_ms = null` for Ollama models, Auto falls back to first-in-list. |
| Cache keyed by `(base_url, provider, model_id)` not `(endpoint_id, model_id)` | `discover-models` runs pre-save (no endpoint_id exists yet). Discovery result populates the cache; saved endpoints key into it by URL+provider. |
| Auto sentinel = `"__auto__"` | Stored as a plain string in the existing `model` varchar column — no migration. Distinct from the existing `LLMIntent.auto` which classifies *intent*, not *model*. Intent classification happens before model routing — no collision. |

---

## Design

### 1. Frontend — `ModelCombobox` component

**New file:** `frontend/src/components/ModelCombobox.tsx`

Replaces the current `discoveredModels.length > 0 ? <select> : <input>` block inside
`LLMEndpointForm.tsx`. The plain text `<input>` (no-discovery fallback) is unchanged.

**Behaviour:**
- Renders a text input (search box) + floating dropdown panel anchored below it.
- **"Auto" is always pinned as the first row**, never filtered out regardless of search text.
  Styled with ⚡ icon and blue tint (`#EFF6FF` background, `#1D4ED8` text).
- Typing filters the model list by **case-insensitive substring match** — no library.
- Each model row: name (monospace) + health badge.
  - Healthy: `● online 28ms` in `#16A34A` (latency shown when available).
  - Unhealthy: `⚠ unreachable` in `#D97706`, row at 40% opacity, `cursor: not-allowed`,
    click is a no-op.
  - Ollama healthy (no latency): `● online` in `#16A34A`, no ms figure.
- A **↺ Refresh** icon button sits beside the "Model" label. Clicking it re-triggers the
  discover+probe call for the current URL.
- Keyboard: ↑/↓ arrows, Enter to select, Escape closes.
- When Auto is selected the stored value is the sentinel string `"__auto__"`.

**Integration in `LLMEndpointForm.tsx`:**
- `discoveredModels` state type: `{id, name, healthy, latency_ms: number | null}[]`.
- When discovery completes and models arrive: render `<ModelCombobox>`.
- When no discovery yet (blank URL): keep existing plain `<input>`.
- **Default selection on discovery**: default to `"__auto__"` (not `models[0].id`). The current
  code at line 93 auto-selects the first model; change this to pre-select Auto instead.
- Auto is always-healthy — never greyed out.

**Display in the endpoint list (SettingsPage):**
When `model === "__auto__"`, render `⚡ Auto` in the model column instead of the raw sentinel.

---

### 2. API — Discovery endpoint

**Endpoint:** `POST /api/v1/llm/discover-models`

**Current response:**
```json
{ "models": [{ "id": "llama3.2", "name": "llama3.2" }] }
```

**New response:**
```json
{
  "models": [
    { "id": "llama3.2",     "name": "llama3.2",     "healthy": true,  "latency_ms": null },
    { "id": "codestral",    "name": "codestral",     "healthy": true,  "latency_ms": null },
    { "id": "llama3.1:70b", "name": "llama3.1:70b", "healthy": false, "latency_ms": null }
  ]
}
```

**Health check logic (backend — `model_discovery.py`):**

- **Ollama**: health = model present in `/api/tags` response (already fetched). No inference probe.
  `latency_ms = null`. A model in the tags list is on disk and Ollama will serve it on demand.
- **vLLM / llamacpp / openai_compat**: after fetching `/v1/models`, run a concurrent 1-token
  inference probe per model (5s timeout via `asyncio.gather`). Health = probe succeeded.
  `latency_ms` = measured round-trip. These providers load models at startup so a 1-token probe
  is cheap and gives real latency data without VRAM side effects.

A model that fails the probe (connection error, timeout, non-200) gets `healthy: false,
latency_ms: null`.

**Cache population**: after running discovery+probe, write results into the health cache keyed by
`(base_url, provider, model_id)` with a 5-minute TTL. This is the only point where the cache
is written — at query time the router reads from it.

**Frontend type update (`frontend/src/api/llm.ts`):**
```ts
discoverModels: (url: string, provider: string) =>
  api.post<{
    models: Array<{
      id: string
      name: string
      healthy: boolean
      latency_ms: number | null
    }>
  }>('/api/v1/llm/discover-models', { url, provider })
```

---

### 3. Backend — Auto router

**Location:** `fleet_platform/api/routes/llm.py` (query dispatch) and
`fleet_platform/api/routes/node_actions.py` (node action dispatch).

**Model health cache:**
In-process dict in a new module `fleet_platform/services/model_health_cache.py`:

```python
# key: (base_url: str, provider: str, model_id: str)
# value: {healthy: bool, latency_ms: int | None, ts: float}
_cache: dict[tuple, dict] = {}
TTL = 300  # 5 minutes

def set_health(base_url, provider, model_id, healthy, latency_ms): ...
def get_healthy_models(base_url, provider) -> list[dict]: ...  # returns [{id, latency_ms}], TTL-filtered
def evict(base_url, provider, model_id): ...  # called on dispatch failure
def is_stale(base_url, provider) -> bool: ...  # true when no entry or all entries expired
```

**Resolving `"__auto__"` at dispatch time (applies to both dispatch sites):**

```
if endpoint.model == "__auto__":
    if cache is stale for (endpoint.base_url, endpoint.provider):
        re-run discover_models() + probes → repopulate cache
    healthy = get_healthy_models(endpoint.base_url, endpoint.provider)
    if not healthy:
        raise HTTP 503 "No healthy models on endpoint '{name}'. Refresh or check URL."
    # pick lowest latency_ms; None latency (Ollama) sorts last
    chosen_model = min(healthy, key=lambda m: m["latency_ms"] or float("inf"))["id"]
else:
    chosen_model = endpoint.model
```

`chosen_model` is then passed to `call_openai_compat()` / `call_anthropic()` in place of
`endpoint.model` at every dispatch site.

**Dispatch sites to update** (all must resolve Auto before calling the provider):
- `fleet_platform/api/routes/llm.py` lines 264, 274 (provider calls), 295, 323 (`model_used`)
- `fleet_platform/api/routes/node_actions.py` lines 368, 377 (provider calls), 391 (`model_used`)

**Dispatch failure → cache eviction:**
If the provider call returns a 4xx/5xx after Auto resolved a model, evict that model's cache entry
and retry routing once with the remaining healthy models. If no models remain after eviction, raise
503. This prevents a 5-minute window where every Auto query routes to a dead model after an
endpoint restart.

**Interaction with existing intent classifier (`llm.py:232–238`):**
Intent classification (`auto` → concrete intent) happens at line 232, before model resolution.
By the time the Auto model router runs, `intent` is already resolved to a concrete value
(e.g. `"salt_state"`). The two `auto` concepts are fully separate: intent-auto classifies the
*task*, model-auto picks the *model*. No collision.

**Observability:**
`model_used` in `LLMQueryResponse` (already exists) records `chosen_model`, not `"__auto__"`.
The query log shows the actual model that served each request.

---

## Data flow summary

```
User types URL
  → 600ms debounce
  → POST /api/v1/llm/discover-models
      → Ollama:  GET /api/tags → mark all listed models healthy, latency_ms=null
      → others:  GET /v1/models → 1-token probe per model (5s timeout, concurrent)
      → cache: (base_url, provider, model_id) → {healthy, latency_ms, ts}
      → returns [{id, name, healthy, latency_ms}]
  → ModelCombobox renders:
      ⚡ Auto (always first, always selectable)
      ● llama3.2     online          (Ollama — no ms)
      ● codestral    online  41ms    (vLLM — probed)
      ⚠ llama3.1:70b  unreachable   (greyed, unselectable)

User selects "Auto" → model saved as "__auto__"

Query arrives (intent may be "auto" or concrete)
  → intent classifier resolves "auto" → "salt_state" (if needed)
  → endpoint.model == "__auto__": read health cache
  → choose lowest-latency healthy model → chosen_model = "codestral"
  → dispatch to provider with model="codestral"
  → on dispatch failure: evict "codestral" from cache, retry with next healthy
  → log model_used = "codestral"
```

---

## Files changed

| File | Change |
|------|--------|
| `frontend/src/components/ModelCombobox.tsx` | New component |
| `frontend/src/components/LLMEndpointForm.tsx` | Replace select/input block with `<ModelCombobox>`; default selection to `"__auto__"`; add refresh trigger |
| `frontend/src/api/llm.ts` | Update `discoverModels` return type |
| `frontend/src/pages/SettingsPage.tsx` | Render `⚡ Auto` when `model === "__auto__"` in endpoint list |
| `fleet_platform/services/model_discovery.py` | Add health check logic; populate health cache; return `{healthy, latency_ms}` per model |
| `fleet_platform/services/model_health_cache.py` | New module — in-process cache with TTL + eviction |
| `fleet_platform/api/routes/llm.py` | Resolve `__auto__` before dispatch at lines 264, 274, 295, 323 |
| `fleet_platform/api/routes/node_actions.py` | Resolve `__auto__` before dispatch at lines 368, 377, 391 |
| `fleet_platform/schemas/llm.py` | Add `healthy`, `latency_ms` to `DiscoveredModel` schema |

---

## Tests required

- **Unit:** `model_health_cache` — TTL expiry, eviction, `get_healthy_models` returns only fresh
  entries, empty result when all stale.
- **Unit:** Auto router — lowest-latency model selected; `None` latency sorts last; 503 on
  all-unhealthy; dispatch-failure triggers eviction + retry.
- **Unit:** `ModelCombobox` — Auto always rendered regardless of filter text; unhealthy models
  unselectable; substring filter; default selection = Auto on first discovery.
- **Integration:** `POST /api/v1/llm/discover-models` returns `healthy` + `latency_ms` fields;
  Ollama path returns `latency_ms: null`.
- **E2E:** Configure endpoint with Auto → send query → `model_used` in query log shows a real
  model id, not `__auto__`.
