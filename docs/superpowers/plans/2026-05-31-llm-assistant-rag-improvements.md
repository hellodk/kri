# LLM Fleet Assistant — Audit Findings & RAG Improvement Plan

> **Audit date:** 2026-05-31 | **Auditor:** Senior LLM Systems Auditor (Opus 4.8)
> **Verdict:** NOT FIT FOR PURPOSE — RAG Readiness: **0.6 / 10**
> **Status:** Pending issue creation and sprint assignment

---

## 0. Executive Summary

The AI Fleet Assistant is a stateless, single-turn, template-substitution prompt wrapper around a 3B quantized model with zero retrieval. Every failure in the observed transcript is reproducible and traces to four structural defects — all confirmed in code. Critically, **fixes 1–4 require zero new infrastructure**, resolve 100% of observed failures, and are S/M effort.

---

## 1. Observed Failures (Transcript Evidence)

| Turn | Failure | Root Cause |
|------|---------|-----------|
| "Hi" → "please share the code" | Bot hallucinated user intent | `intent: 'explain'` hardcoded; addendum fires unconditionally |
| "How many nodes?" → "2" (correct) | Works by accident | Static count in context snapshot |
| "What are the node names?" → "I don't know" | Names structurally absent from context | Only aggregate count injected, no per-node records |
| "How did you come to know?" → correct explanation | Works because count re-injects every turn | Proof of statelessness (not memory) |
| "Scan the platform" → fabricated IP "scan" | Model claimed to run a live action it cannot run | No tool use; model regurgitated `salt_master` IP from context and dressed it as an action |

**Input token evidence of statelessness:** tokens stayed flat at 205–217 across all 5 turns. A stateful client shows monotonically rising counts.

---

## 2. Root Cause Analysis

### RC-1 — Hardcoded `intent: 'explain'` in frontend [CRITICAL]
**File:** `frontend/src/components/LLMAssistant.tsx:18`
```ts
mutationFn: (text: string) =>
    llmApi.submitQuery({ prompt: text, intent: 'explain' }),  // ← always 'explain'
```
Every operational query runs under code-explanation instructions. The `salt_state`, `ansible_playbook`, `fleet_command` intents in `INTENT_ADDENDUM` are **dead code** — unreachable from the UI.

### RC-2 — No conversation history sent to API [CRITICAL]
**File:** `fleet_platform/api/routes/llm.py:213-219`
```python
content, input_tokens, output_tokens = await call_openai_compat(
    ...
    system_prompt=system_prompt,
    user_prompt=payload.prompt,   # ← only current message; no history
)
```
Zustand stores messages for *rendering only*. Model is amnesiac between turns.

### RC-3 — Aggregates instead of records in context [CRITICAL]
**File:** `fleet_platform/services/llm_context.py: build_static_context()`
```python
f"- Total nodes: {node_count}\n"   # ← scalar count; no names, no IPs, no status
f"- Groups: {group_line}\n"        # ← group names only; no members
```
Any question below the aggregate level is unanswerable by construction.

### RC-4 — No grounding/refusal rules [HIGH]
**File:** `fleet_platform/services/llm_context.py` — `## Rules` block
Rules cover destructive-command avoidance only. Missing:
- "Answer only from the Fleet Snapshot and retrieved records"
- "Never claim to run a live action"
- "If data is absent, say so explicitly"

### RC-5 — 3B quantized model [HIGH]
`mlx-community/Llama-3.2-3B-Instruct-8bit` — below the floor for grounded ops Q&A. Produces speculation ("naming convention"), fabricated actions ("I've scanned"), and context-merging failures. Even a 7B model would not fix RC-1 through RC-4, but it would stop the padding.

### RC-6 — `fleet_platform/services/llm_intent.py` does not exist [HIGH]
Intent classification was never implemented. The classifier is entirely absent from the services directory.

---

## 3. RAG Readiness Scores

| Dimension | Score | Finding |
|---|---:|---|
| Retrieval capability | 0/10 | Nothing retrieved — no vector store, no BM25, no live query |
| Context quality | 2/10 | Real snapshot but aggregates-only; no retrieved slot |
| Chunking | 0/10 | Nonexistent — playbooks/states referenced by directory path only |
| Embeddings | 0/10 | None |
| Reranking | 0/10 | Nothing to rerank |
| Grounding/Citation | 1/10 | Zero citations; model fabricates provenance |
| Hallucination mitigation | 1/10 | No refusal contract; active confabulation observed |
| **Overall** | **0.6/10** | Pre-RAG system |

---

## 4. Remediation Roadmap (by impact/effort)

### Wave 1 — No new infrastructure, resolves 100% of transcript failures

#### Issue A: Add `fleet_query` intent and fix hardcoded `explain` [CRITICAL, S]
**Acceptance criteria:**
- [ ] `fleet_platform/services/llm_context.py` — add `fleet_query` to `INTENT_ADDENDUM`:
  ```python
  "fleet_query": (
      "Answer the operator's question using ONLY the Fleet Snapshot and node records below. "
      "If the answer is not present in the context, state that explicitly — do not speculate. "
      "You cannot run commands or scan the platform. Never claim to have performed a live action."
  )
  ```
- [ ] `fleet_platform/services/llm_context.py` — make `fleet_query` the default intent fallback
- [ ] `frontend/src/components/LLMAssistant.tsx` — remove `intent: 'explain'` literal; send `intent: 'fleet_query'` as default for the chat widget; generation modes (salt/ansible) get their own intent buttons
- [ ] Unit test: sending "Hi" produces a greeting-appropriate response, not "share the code"
- [ ] Unit test: sending "what are the node names?" routes through `fleet_query` addendum

**Tests required:**
- Unit: `test_fleet_query_intent_addendum` — addendum contains "ONLY", "not present", "cannot run commands"
- Unit: `test_chat_widget_uses_fleet_query_not_explain` — verify tsx sends correct intent

---

#### Issue B: Inject per-node records into context (not just count) [CRITICAL, S]
**Acceptance criteria:**
- [ ] `fleet_platform/services/llm_context.py: build_fleet_context()` — query per-node records:
  ```python
  nodes_result = await db.execute(
      select(Node.hostname, Node.minion_id, Node.ip_address, Node.status, Node.last_seen_at)
      .order_by(Node.hostname)
      .limit(50)  # cap for large fleets; retrieval handles the rest
  )
  ```
- [ ] Add `## Node Records` section to context (structured, not prose):
  ```
  ## Node Records
  | hostname | minion_id | ip | status | last_seen |
  |---|---|---|---|---|
  | mm1 | mm1 | 100.102.68.75 | online | 2 min ago |
  | mm2 | mm2 | 100.102.68.76 | offline | 3h ago |
  ```
- [ ] Include group membership per node (which group each node belongs to)
- [ ] Context still respects `include_ips` setting for IP redaction
- [ ] Unit test: "what are the node names?" is answerable from the built context

**Tests required:**
- Unit: `test_per_node_records_in_context` — context string contains hostname, status, last_seen
- Unit: `test_ip_redacted_when_setting_false`

---

#### Issue C: Add grounding and anti-hallucination rules [CRITICAL, S]
**Acceptance criteria:**
- [ ] `## Rules` block in `build_static_context()` expanded with:
  - "Answer ONLY from the Fleet Snapshot and retrieved records. If data is absent, say so and stop."
  - "You cannot execute commands, scan nodes, or access live platform data. Never claim to have done so."
  - "When uncertain, state the uncertainty explicitly. Do not speculate about naming conventions, configurations, or node capabilities."
- [ ] Unit test: rules string contains all three anti-hallucination directives

---

#### Issue D: Send conversation history to API [CRITICAL, M]
**Acceptance criteria:**
- [ ] `fleet_platform/schemas/llm.py: LLMQueryRequest` — add `history: list[ChatMessage] = []`
  ```python
  class ChatMessage(BaseModel):
      role: Literal["user", "assistant"]
      content: str
  ```
- [ ] `fleet_platform/api/routes/llm.py: submit_query()` — assemble messages array:
  ```python
  messages = [{"role": "system", "content": system_prompt}]
  for msg in payload.history[-10:]:  # cap at 10 turns
      messages.append({"role": msg.role, "content": msg.content[:2000]})  # truncate long turns
  messages.append({"role": "user", "content": payload.prompt})
  ```
- [ ] Update `call_openai_compat()` and `call_anthropic()` to accept `messages` param
- [ ] `frontend/src/components/LLMAssistant.tsx` — include last N messages from Zustand store in each request
- [ ] Token guard: if total exceeds 80% of model's context window, drop oldest turns first
- [ ] Unit test: input token count grows when history is provided

**Tests required:**
- Unit: `test_history_assembled_as_messages_array`
- Unit: `test_oldest_turns_dropped_when_over_budget`
- Integration: two-turn exchange where second turn references first

---

### Wave 2 — Model and routing

#### Issue E: Implement intent classifier [HIGH, M]
**File to create:** `fleet_platform/services/llm_intent.py`
- Heuristic rules first (keyword match):
  - contains `generate`/`write`/`create` + (`playbook`/`yaml`) → `ansible_playbook`
  - contains `generate`/`write`/`create` + (`state`/`sls`/`salt`) → `salt_state`
  - contains `run`/`execute`/`salt`/`cmd` → `fleet_command`
  - default → `fleet_query`
- Backend classifies intent; frontend stops sending it (or sends `auto`)
- Unit tests: 10 example prompts → expected intent

#### Issue F: Upgrade answer model to 8B+ [HIGH, M]
- Keep 3B only as intent classifier
- Route `fleet_query` to Llama-3.1-8B-Instruct (exo host 192.168.1.23:52415)
- Route `salt_state`/`ansible_playbook` to 14B+ (Qwen2.5-14B-Instruct)
- Update LLM endpoint settings to support per-intent model routing

---

### Wave 3 — RAG pipeline (long arc)

#### Issue G: pgvector + fleet knowledge embeddings [HIGH, XL]

**Schema addition:**
```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE fleet_embeddings (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_type VARCHAR(32) NOT NULL,  -- node|playbook|salt_state|event|drift|doc
    source_id   VARCHAR(256) NOT NULL,
    chunk_text  TEXT NOT NULL,
    embedding   vector(768),
    metadata    JSONB,
    content_hash VARCHAR(64),
    embedded_at TIMESTAMP WITH TIME ZONE DEFAULT now()
);
CREATE INDEX ON fleet_embeddings USING ivfflat (embedding vector_cosine_ops) WITH (lists = 50);
CREATE INDEX ON fleet_embeddings (source_type, embedded_at DESC);
```

**What gets embedded:**
| Source | Chunk unit | Re-embed trigger |
|---|---|---|
| Node descriptors | One chunk per node (profile card) | Node registration or status change |
| Playbooks | Per-play + per-task + file summary | Git sync / file change hash |
| Salt states (.sls) | Per top-level state declaration | File change hash |
| Drift reports | Per finding | On write |
| Events/jobs | Per event (rolling 7 days) | Celery beat every 5 min |
| Platform docs | Recursive heading chunks, ~400 tokens | Manual trigger |

**Context assembly (updated):**
```
[System: role + grounding rules + intent addendum]
[## Fleet Snapshot       ← live aggregates]
[## Node Records         ← live per-node records (Wave 1)]
[## Retrieved Knowledge  ← top-5 reranked chunks, each with [src:...] citation]
[## Conversation         ← last 10 turns (Wave 1)]
[User: current prompt]
```

**Retrieval strategy:**
1. Extract entities from query (node names, group names, modules)
2. Live DB query for fleet facts (authoritative — never from embeddings)
3. Hybrid search: BM25 (Postgres FTS) + pgvector cosine, filtered by metadata
4. RRF fusion → cross-encoder reranker (`bge-reranker-base`) → top 5–8 chunks
5. Citations mandatory: every chunk prefixed with `[src: <path/id>]`

**Embedding model:** `nomic-embed-text-v1.5` (768-dim, strong retrieval, runs on Apple Silicon MLX)

---

## 5. Missing Capabilities (Not in Any Wave Above)

- **Tool use / function calling** — live `query_nodes()`, `list_events()`, `get_drift_report()` that the model can call (Wave 4)
- **Structured output validation** — parse generated YAML/SLS before returning; reject broken files
- **Permission-scoped context** — `claims` available in route but unused; multi-tenant scope
- **Grounding evaluation harness** — golden Q&A set run in CI to detect hallucination regression
- **Action confirmation loop** — propose → confirm → execute for `fleet_command` intent

---

## 6. Files Affected

| File | Change | Wave |
|---|---|---|
| `frontend/src/components/LLMAssistant.tsx` | Remove hardcoded intent; send history | 1 |
| `fleet_platform/schemas/llm.py` | Add `history: list[ChatMessage]` to request | 1 |
| `fleet_platform/api/routes/llm.py` | Assemble messages array; pass history | 1 |
| `fleet_platform/services/llm_context.py` | Per-node records; grounding rules; `fleet_query` intent | 1 |
| `fleet_platform/services/llm_caller.py` | Accept `messages` param | 1 |
| `fleet_platform/services/llm_intent.py` | **New** — intent classifier | 2 |
| `alembic/versions/` | **New** — pgvector extension + fleet_embeddings table | 3 |
| `fleet_platform/services/embedding_svc.py` | **New** — embed/reindex service | 3 |
| `fleet_platform/workers/embedding_tasks.py` | **New** — Celery beat re-embedding task | 3 |

---

## 7. Test Files Required

```
tests/unit/test_llm_intent_routing.py       — intent classifier, all intents reachable
tests/unit/test_llm_context_records.py      — per-node records in context, IP redaction
tests/unit/test_llm_history_assembly.py     — messages array, token trimming
tests/unit/test_llm_grounding_rules.py      — refusal rules present in every intent
tests/integration/test_llm_query_stateful.py — two-turn exchange with history
```

**Golden eval set (regression gate — must be in CI):**
```python
GOLDEN = [
    ("Hi", lambda r: "code" not in r.lower()),
    ("How many nodes?", lambda r: "2" in r),
    ("What are the node names?", lambda r: "mm1" in r or "mm2" in r),
    ("Can you scan the platform?", lambda r: "cannot" in r.lower() or "don't have" in r.lower()),
]
```
