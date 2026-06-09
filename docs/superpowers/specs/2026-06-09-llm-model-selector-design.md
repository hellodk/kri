# LLM Endpoint Model Selector — Design Spec

**Date:** 2026-06-09
**Status:** Draft — pending review

---

## Problem

LLM endpoints (Ollama, vLLM, llama.cpp) often serve multiple models. The current form forces the user to type a model name manually or pick from a plain `<select>` with no search. There is no way to:

1. Let a smart router pick the best model automatically based on intent.
2. Search a large model list (30–50 models) quickly.
3. Know which models are actually reachable before saving.

---

## Goals

1. Add **Auto mode** — a sentinel model choice where the backend router picks the best healthy model per request based on intent.
2. Add **fuzzy/substring search** in the model dropdown when models have been discovered.
3. Add **health probing** — discover and probe all models concurrently on URL entry; grey out unreachable models before the user selects one.

---

## Out of Scope

- Per-intent model override UI (possible future use of the toggle from Option B — not in this spec).
- Persistent health polling (background poller every N seconds — explicitly rejected due to performance cost).
- Changes to provider list or API key handling.

---

## Design

### 1. Frontend — `ModelCombobox` component

**New file:** `frontend/src/components/ModelCombobox.tsx`

Replaces the current `discoveredModels.length > 0 ? <select> : <input>` block inside `LLMEndpointForm.tsx`. The plain text `<input>` (no-discovery fallback) is unchanged.

**Behaviour:**
- Renders a text input (search box) + floating dropdown panel anchored below it.
- **"Auto" is always pinned as the first row**, never filtered out regardless of search text. Styled with ⚡ icon and blue tint (`#EFF6FF` background, `#1D4ED8` text).
- Typing filters the model list by **case-insensitive substring match** — no third-party library. Model names (`llama3.2:8b`, `qwen2.5:72b-instruct`) are well-served by substring.
- Each model row: name (monospace) + health badge.
  - Healthy: `● online 28ms` in `#16A34A`.
  - Unhealthy: `⚠ timeout` in `#D97706`, row at 40% opacity, `cursor: not-allowed`, click is a no-op.
- A **↺ Refresh** icon button sits beside the "Model" label. Clicking it re-triggers the discover+probe call for the current URL.
- Keyboard navigation: ↑/↓ arrows, Enter to select, Escape to close.
- When Auto is selected the stored value is the sentinel string `"__auto__"`.

**Integration in `LLMEndpointForm.tsx`:**
- The `discoveredModels` state type changes from `{id, name}[]` to `{id, name, healthy, latency_ms}[]`.
- When discovery completes and `discoveredModels.length > 0`: render `<ModelCombobox>`.
- When no discovery yet (blank URL): keep existing plain `<input>`.
- Auto is treated as always-healthy — it is never greyed out.

**Display in the endpoint list (SettingsPage):**
When `model === "__auto__"`, render `⚡ Auto` in the model column instead of the raw sentinel string.

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
    { "id": "llama3.2",     "name": "llama3.2",     "healthy": true,  "latency_ms": 28  },
    { "id": "llama3.1:70b", "name": "llama3.1:70b", "healthy": false, "latency_ms": null },
    { "id": "codestral",    "name": "codestral",     "healthy": true,  "latency_ms": 41  }
  ]
}
```

**Probe logic (backend):**
After fetching the model list from the endpoint, run a minimal chat completion request per model (1 output token, empty system prompt) with a **5-second timeout**, using `asyncio.gather` for full concurrency. Total wall-clock = slowest single probe, not the sum.

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

**Auto sentinel:**
`"__auto__"` is stored as the `model` string in the database and passed through the API unchanged. No schema migration is required — it is a valid string value in the existing `model` column. The backend router recognises it at query dispatch time.

---

### 3. Backend — Smart Router for Auto mode

**Location:** `fleet_platform/services/llm_svc.py`

**Model health cache:**
An in-process dict keyed by `(endpoint_id, model_id)` with a **5-minute TTL**. Populated whenever `discover-models` is called for a given endpoint. At query time the router reads from cache — no extra HTTP call unless the entry is stale or missing.

**Routing logic:**

```python
INTENT_PREFERENCE: dict[str, list[str]] = {
    "salt_state":       ["capability:code", "context:long"],
    "ansible_playbook": ["capability:code", "context:long"],
    "fleet_command":    ["capability:code"],
    "explain":          ["context:short"],
    "fleet_query":      ["capability:reasoning"],
    "auto":             [],   # no preference — first healthy wins
}
```

When `model == "__auto__"`:
1. Fetch healthy models for the endpoint from the health cache (re-probe if stale).
2. Score each healthy model: +1 per matching tag from the intent's preference list. Tags are derived from the `model_capabilities` and `model_context_length` fields already on `LLMEndpoint`.
3. Select the highest-scoring model. Ties broken by lowest `latency_ms`.
4. If **no healthy models exist**: raise HTTP 503 — `"No healthy models available on endpoint '{name}'. Refresh model status or check the endpoint URL."`

**Observability:**
The existing `model_used` field in `LLMQueryResponse` already records the actual model string. When Auto is active it logs the model the router selected — visible in the query log in the UI.

---

## Data flow summary

```
User types URL
  → 600ms debounce
  → POST /api/v1/llm/discover-models
      → backend fetches model list from endpoint
      → asyncio.gather: probe each model (5s timeout)
      → returns [{id, name, healthy, latency_ms}]
  → ModelCombobox renders:
      ⚡ Auto (always first, always selectable)
      ● llama3.2     online  28ms
      ● codestral    online  41ms
      ⚠ llama3.1:70b  timeout  (greyed, unselectable)

User selects "Auto" → model saved as "__auto__"

Query arrives with intent="salt_state"
  → llm_svc reads health cache for endpoint
  → scores healthy models by INTENT_PREFERENCE["salt_state"]
  → dispatches to best match
  → logs model_used = "codestral" (whichever won)
```

---

## Files changed

| File | Change |
|------|--------|
| `frontend/src/components/ModelCombobox.tsx` | New component |
| `frontend/src/components/LLMEndpointForm.tsx` | Replace select/input block with `<ModelCombobox>`, add refresh trigger |
| `frontend/src/api/llm.ts` | Update `discoverModels` return type |
| `frontend/src/pages/SettingsPage.tsx` | Render `⚡ Auto` when `model === "__auto__"` in endpoint list |
| `fleet_platform/routers/llm.py` | Update `discover-models` handler to probe + return health |
| `fleet_platform/services/llm_svc.py` | Add health cache, Auto routing logic |
| `fleet_platform/schemas/llm.py` | Add `healthy`, `latency_ms` to `DiscoveredModel` schema |

---

## Tests required

- **Unit:** Router scoring logic — correct model selected per intent, 503 on all-unhealthy.
- **Unit:** Health cache TTL — stale entries trigger re-probe.
- **Unit:** `ModelCombobox` — Auto always rendered, unhealthy models unselectable, substring filter works.
- **Integration:** `POST /api/v1/llm/discover-models` returns health fields; unhealthy model does not appear selectable in form.
- **E2E:** Configure endpoint with Auto → send query → `model_used` in query log shows a real model name, not `__auto__`.
