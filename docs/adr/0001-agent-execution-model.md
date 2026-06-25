# 1. Agent execution model: in-handler SSE vs. durable off-event-loop

- **Status:** Accepted
- **Date:** 2026-06-25
- **Deciders:** Platform / SRE
- **Issue:** Closes #880 (lineage: #650, #711, #716)

## Context

The agent run loop currently executes **inside the FastAPI request handler**.
`POST /api/v1/agent/run/stream` (`fleet_platform/api/routes/agent.py::run_agent_stream`)
opens an `AgentSession`, builds the planner + bounded loop, and then returns a
`StreamingResponse` whose async generator drives the whole multi-tool turn,
emitting `session_start` / `step_start` / `tool_call` / `tool_result` /
`awaiting_approval` / `final` / `done` frames as Server-Sent Events. The request
coroutine — and everything it holds — stays alive for the *entire* run.

What the run holds open for its full wall time:

- **One async DB connection.** The `db: AsyncSession` dependency is injected once
  and used throughout `event_stream()` (session open, proposal creation, final
  `commit`). It is checked out of the pool for the whole run, not per-query.
- **One SSE/HTTP connection** from client → ingress → API pod.
- **One in-process tier-router lease** (`tier_router.lease(endpoint)`), an
  in-memory in-flight counter that is **per-worker and non-durable** — it is lost
  on restart and not shared across replicas.

The loop is already **bounded** (`fleet_platform/agent/loop.py`):

- `MAX_ITERATIONS = 6`, `MAX_TOOL_CALLS = 12` per run.
- A no-progress guard stops a planner that repeats identical tool calls.
- A client-disconnect check runs before every iteration.
- Every bounded/stalled stop still emits a terminal `final` frame.

The endpoint is **rate-limited `6/minute`** (per client, via `limiter.limit`) and
gated by `require_role("operator", "admin")`. Wall time per run is dominated by
**planner latency** (LLM calls to the local-MLX planner tier), not by tool
execution: each iteration is one planner round-trip plus ≤ a few fast read-only
tool calls.

### The original concern (#650 lineage)

SRE flagged a FastAPI **pool-exhaustion / "2am page"** risk: under concurrent
long-running agent turns, in-handler execution pins request-scoped resources for
the run duration, and a burst could starve the rest of the API. The proposed
remedy was a **durable Celery state machine** (persisted step state) with the
frontend **polling/subscribing** instead of holding an SSE connection.

### Current deployment (the numbers that matter)

From `deploy/k8s/`:

| Resource | Value | Source |
|---|---|---|
| API replicas | `2` (HPA `min 2 → max 5`) | `api-deployment.yaml`, `hpa.yaml` |
| Uvicorn workers / replica | **1** (no `--workers` flag; single async event loop) | `api-deployment.yaml` cmd |
| Async DB pool / process | `pool_size=10`, `max_overflow=20`, `pool_timeout=30s` | `fleet_platform/db/session.py` |
| Hard DB conns / replica | `30` (10 + 20 overflow) | derived |
| Rate limit | `6 / minute` per client | `routes/agent.py` |
| Loop bounds | `6` iterations, `12` tool calls | `agent/loop.py` |
| Celery (already deployed) | sync pool `5 + 10`, 2 worker replicas (HPA → 4) | `db/session.py`, `worker-deployment.yaml` |

Note the system is **async**: a single uvicorn worker multiplexes many
coroutines on one event loop, and planner calls are `await`ed I/O — so a slow
planner does **not** block the loop. The binding constraint is therefore **not**
CPU "workers" in the classic blocking-WSGI sense; it is the **number of
concurrently in-flight runs each pinning one pooled DB connection** (plus open
SSE sockets and file descriptors).

## Quantitative framing

Treat each in-flight agent run as occupying one unit of a finite resource (a
pooled DB connection) for its wall time. By Little's Law the steady-state number
of concurrent in-flight runs is:

```
concurrent_sessions (L) = arrival_rate (λ) × avg_run_wall_time (W)
worker_occupancy        = concurrent_sessions × avg_run_wall_time   (resource-seconds)
```

Saturation occurs when `concurrent_sessions` exceeds the **safe** connection
budget the agent endpoint may consume without starving the rest of the API.

**Capacity.** Per replica the hard ceiling is 30 connections, but they are shared
with every other endpoint. Reserving roughly one third for the agent gives a safe
budget of ≈ **5 concurrent agent runs/replica** before runs start drawing on
overflow and risking `pool_timeout` (30s) failures *for unrelated traffic*:

```
safe_agent_capacity  = replicas × ~5   = 2 × 5  = 10   (today)
                                          5 × 5  = 25   (HPA fully scaled)
hard_ceiling         = replicas × 30  = 60 conns (but degrades everything past safe budget)
```

**Saturation concurrency vs. wall time.** Required concurrency `L = λ × W`. With
the `6/min` per-user limit and **per-user concurrency = 1** (see decision), each
distinct active operator contributes at most one in-flight run, so
`concurrent_sessions ≈ number of simultaneously-active operators`, independent of
`W`:

| Avg run wall time `W` | Per-operator sustainable rate | Distinct operators to reach safe cap (10) | Distinct operators to reach hard ceiling (60) |
|---|---|---|---|
| 5 s | ≤ 6/min (rate-limit bound) | 10 | 60 |
| 15 s | ≤ 4/min | 10 | 60 |
| 30 s | ≤ 2/min | 10 | 60 |
| 60 s | ≤ 1/min | 10 | 60 |

The key result: **with per-user concurrency = 1, wall time stops driving the
concurrency ceiling** — it only changes how long each of the (≤ operator-count)
slots is held. Saturation of the safe budget needs **~10 distinct operators
running agent turns at the same instant** (≈25 at full HPA scale). For a fleet
platform whose operator pool is single- to low-double-digit, this is comfortably
under threshold. Without a per-user cap, a single scripted caller at `6/min` with
`W = 30s` would instead hold up to `6/min × 30s = 3` slots alone, and a handful of
such callers would reach the safe budget — which is exactly the #650 risk.

## Options

### Option A — Keep SSE in-handler, with documented tuning (status quo, hardened)

Keep the loop in the request handler and SSE to the browser. Make the safety
properties explicit and enforced:

- **Feature gate:** `AGENT_ENABLED` (default off) so the endpoint can be killed
  instantly without a redeploy.
- **Per-user session concurrency = 1:** reject (HTTP 409) a second concurrent
  run for the same user. Caps in-flight runs at the active-operator count.
- **Documented tuning knobs:** API replicas / HPA bounds, DB `pool_size` /
  `max_overflow`, and the `6/min` rate limit — sized against the table above.
- Keep the existing bounds (6 iter / 12 tools), disconnect check, and terminal
  `final` frame.

**Pros:** zero new infrastructure; lowest latency (token-time-to-first-frame);
preserves the live step-by-step transcript UX; trivially revertible via the flag.
**Cons:** a run still pins a connection + socket for its wall time; resilience is
bounded by the per-user cap and rate limit; an API rollout interrupts in-flight
runs (the client must restart the turn).

### Option B — Durable, off-event-loop execution

Move the loop into a background worker (Celery already runs — `worker-deployment.yaml`,
sync pool `5 + 10`). The handler enqueues a job and returns immediately; step
state is persisted on `AgentSession` (a `steps`/`status`/`cursor` representation),
and the frontend **polls** `GET /agent/sessions/{id}` (or subscribes via a thin
SSE relay over the persisted log).

**Pros:** request handler returns in ms (no long-held request resources);
survives API rollouts and pod restarts; durable, replayable transcript; in-flight
accounting can become cross-replica/durable instead of the per-worker
`tier_router` lease.
**Cons:** real build — DB schema for step state, worker plumbing, a poll/subscribe
API, idempotency + resumption, and frontend rework from live-SSE to poll; adds
end-to-end latency and a new failure surface (broker, stuck jobs → already need a
reaper, cf. `reap_stuck_pending_actions`). Approval/co-sign flow
(`awaiting_approval` → `PendingAction`) must be re-expressed as a durable pause.

## Decision

**Adopt Option A now.** Keep the agent loop in the request handler with SSE,
**gated by `AGENT_ENABLED` and enforced per-user concurrency = 1**, plus the
existing bounds and `6/min` rate limit. Document the tuning knobs (replicas/HPA,
DB pool, rate limit) as the operational levers.

**Defer Option B** until a stated, measurable threshold is crossed.

### Rationale

- The dominant #650 risk vector — unbounded concurrent runs pinning request
  resources — is closed by **per-user concurrency = 1** + the rate limit:
  in-flight runs ≤ active-operator count, which the table shows sits well under
  the safe DB-pool budget for any realistic operator count.
- The async event loop means a slow planner does not block other requests; the
  scarce resource is pooled DB connections, and the cap bounds it directly.
- Option B is a multi-week build with a new failure surface; spending it now is
  unjustified without evidence the bound is actually being approached.

### Revisit trigger (concrete & falsifiable)

Re-open and implement Option B if **any** of these hold for a sustained window
(≥ 1 week, observed in metrics/load test — not anecdotally):

1. **Concurrency:** peak concurrent in-flight agent runs ≥ **8 per replica**
   (i.e. ≥ 80% of the ~10-run safe budget at `replicas=2`), **or** API DB
   `pool_timeout` errors attributable to agent traffic occur at all.
2. **Latency:** p95 agent-run wall time `W` ≥ **45 s** on the local-MLX planner
   tier (long-held connections amplify the concurrency pressure above).
3. **Availability:** in-flight runs interrupted by API rollouts become a
   recurring operator complaint (durability becomes a feature requirement, not
   just a scaling one).

If none of these trip, Option A stands.

## Next step (do this before any rebuild)

**Run the load test, don't guess.** Before committing to Option B, measure the
real numbers against the framing above using `scripts/agent_loadtest.py`:

```bash
# Fire N concurrent /api/v1/agent/run/stream requests; report p50/p95 wall time
# and max observed in-flight. Manual tool — see the script header.
python scripts/agent_loadtest.py \
  --base-url https://kri.local --token "$KRI_TOKEN" \
  --concurrency 12 --total 60 --prompt "why is mm7 degraded?"
```

Compare the observed **max in-flight** and **p95 wall time** to the revisit
triggers. Watch API DB-pool saturation (`pool_timeout` logs) and HPA behaviour
during the run. Only if a trigger fires do we schedule the Option B build.

## References

- `fleet_platform/api/routes/agent.py` — `run_agent_stream` (in-handler SSE).
- `fleet_platform/agent/loop.py` — bounded loop (6 iter / 12 tools).
- `fleet_platform/db/session.py` — async pool `10 + 20`, sync pool `5 + 10`.
- `deploy/k8s/{api-deployment,hpa,worker-deployment}.yaml` — replicas / HPA.
- `fleet_platform/services/tier_router.py` — per-worker in-flight lease.
- `scripts/agent_loadtest.py` — the load test referenced above.
- Issues: #880 (this ADR), #650 (SRE concern), #711 / #716 (agent loop + bounds).
