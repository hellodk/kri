# Agent Model Usage Guide

How the kri agent uses local LLMs: which models power each tier, why they were
chosen, how requests are routed to them, and how to size/swap them for your own
hardware.

> Source of truth for config: `salt/pillar/ml/tiers/*.sls`,
> `salt/states/ml/mlx_serve/`, `fleet_platform/services/tier_router.py`,
> `fleet_platform/services/cost_tracker.py`. Roll-out steps live in
> `docs/runbooks/mlx-cluster.md`.

---

## TL;DR — recommended models

All tiers run **4-bit MLX** builds of the **Qwen2.5** family, served from the
18× M4 Mac mini fleet (16 GB each) as OpenAI-compatible endpoints.

| Tier | Model (4-bit MLX) | Role | Minions | Port | max_concurrent | Capability tag |
|---|---|---|---|---|---|---|
| **Planner** | `mlx-community/Qwen2.5-14B-Instruct-4bit` | Plans, selects tools, reasons | mm1, mm2 | 8080 | 1 | `planner` |
| **Coder** | `mlx-community/Qwen2.5-Coder-14B-Instruct-4bit` | Authors Ansible/Salt YAML | mm3–mm6 | 8080 | 1 | `coder_yaml,coder` |
| **Worker** | `mlx-community/Qwen2.5-7B-Instruct-4bit` | Fast summarize / light steps | mm7–mm16 | 8080 | 2 | `fast_summarize,worker` |
| **Embed** | `mlx-community/bge-m3-4bit` | Embeddings for RAG/search | mm17, mm18 | 8081 | 4 | `embed` |

---

## Why these models

- **Qwen2.5 family, 4-bit quantization** — best quality-per-GB for the agent's
  two hot paths (tool-calling/reasoning and YAML/code authoring) that still fits
  comfortably in 16 GB of unified memory.
- **14B planner / 14B coder, 7B worker** — the agent's brain and artifact-author
  need stronger reasoning; high-volume summarization is offloaded to the cheaper
  7B worker tier so planners stay free.
- **bge-m3 for embeddings** — strong multilingual retrieval model; runs as a
  sidecar on a worker subset and **never on planners** to keep planner RAM free.

### 16 GB is tight — the guardrails that make 14B-4bit safe
- Planner/coder stay at `max_concurrent: 1`.
- Per-session **context cap of 8192 tokens** (512 for embed).
- Hard agent bounds in `fleet_platform/agent/loop.py`:
  `MAX_ITERATIONS = 6`, `MAX_TOOL_CALLS = 12`.
- Tool results are truncated at `TOOL_RESULT_CAP = 4096` bytes before being fed
  back to the planner (`fleet_platform/agent/planner.py`).

---

## How a request reaches a model

The **tier router** (`fleet_platform/services/tier_router.py`) maps a required
capability to a concrete endpoint by walking a fallback chain of tags, filtering
to **enabled + healthy** endpoints, and choosing the **least-loaded** one.

```
planner        → planner → general
coder_yaml     → coder_yaml → coder → general
fast_summarize → fast_summarize → worker → general
embed          → embed
```

- The agent route auto-selects a **planner**-tier endpoint when no `endpoint_id`
  is supplied (`agent.py`: `select_endpoint(db, "planner", allow_cloud=...)`).
- **Health:** a probe/call failure marks an endpoint unhealthy for a **60 s**
  cooldown; new sessions steer to the next-least-loaded healthy endpoint.
- **Load:** an in-flight lease counter implements least-loaded selection with no
  external metrics backend (per API worker process).

### Cloud fallback (off by default)
The chain ends at an optional `cloud`-tagged endpoint, used **only**:
1. for **admin** sessions (`allow_cloud = role == "admin"`), **and**
2. when **every** local tier is unhealthy, **and**
3. when the **daily spend cap** has not been exhausted.

Cost guard (`fleet_platform/services/cost_tracker.py`):

| Setting | Env var | Default |
|---|---|---|
| Blended cloud price | `AGENT_CLOUD_COST_PER_1K_USD` | `0.009` /1K tokens |
| Daily spend cap | `AGENT_CLOUD_DAILY_CAP_USD` | `5.0` USD |

Once the day's cloud spend hits the cap, `can_spend()` returns false and the
router refuses to route to cloud — a degraded local cluster can never run up an
unbounded bill.

---

## Deploying the models

```bash
# 1. Stage pillar + state tops (one-time)
cp salt/pillar/top.sls.example salt/pillar/top.sls
cp salt/states/top.sls.example salt/states/top.sls

# 2. Apply the serving state per tier (canary first)
salt 'mm1' state.apply ml.mlx_serve            # planner canary
salt 'mm3' state.apply ml.mlx_serve            # coder canary
salt 'mm7' state.apply ml.mlx_serve            # worker canary

# 3. Benchmark canaries against the Phase-C gates
python scripts/mlx_bench.py --base-url http://mm1:8080/v1 --model qwen2.5-14b      --tier planner --runs 20
python scripts/mlx_bench.py --base-url http://mm3:8080/v1 --model qwen2.5-coder-14b --tier coder   --runs 20

# 4. If gates pass, roll out to all 18
salt 'mm*' state.apply ml.mlx_serve
```

The MLX serving state pulls the model named in each minion's pillar, so the
model files are fetched on first `state.apply` per tier.

### Register endpoints in kri
For each serving minion, create an `LLMEndpoint` (**Settings → LLM**) pointing at
`http://<minion>:<port>/v1` and set **model_capabilities** to the tier tag:

| Tier | `model_capabilities` | Extra |
|---|---|---|
| Planner | `planner` | — |
| Coder | `coder_yaml,coder` | — |
| Worker | `fast_summarize,worker` | — |
| Embed | `embed` | also set `LLM_EMBED_BASE_URL` (Settings) |

---

## Observability

- `GET /api/v1/agent/tiers` — live snapshot per tier: endpoints, matched tag,
  health, in-flight load.
- `GET /api/v1/agent/costs` — today's cloud spend, daily cap, remaining, capped flag.

---

## Performance gates (Phase C done-when)

- ≥ 95% of queries served locally
- p95 first-token ≤ 2.5 s on the local planner
- $0 token cost

Failover smoke test:

```bash
salt 'mm1' service.stop ai.kri.mlx.planner   # take a planner offline
# new agent runs route to mm2 (or 'general'); GET /agent/tiers shows mm1 unhealthy
```

---

## Adapting to different hardware

The defaults target 18× 16 GB M4 minis. If your inventory differs:

| Scenario | Suggested adjustment |
|---|---|
| **Fewer minions** | Co-locate tiers: serve `planner` + `worker` from one node by tagging a single endpoint `planner,worker,fast_summarize,general`. Keep embed separate if possible. |
| **32–64 GB machines** | Raise planner `max_concurrent` to 2–3, lift `context_cap`, or step the planner up to a less-quantized 14B (8-bit) or a `Qwen2.5-32B-Instruct-4bit`. |
| **Single workstation** | Run one endpoint tagged `planner,coder_yaml,coder,fast_summarize,worker,general` with a 14B-4bit; point `embed` at the same box or a small `bge-small`. |
| **GPU / non-Mac** | Serve the same Qwen2.5 weights via any OpenAI-compatible server (vLLM, Ollama, TGI); only the `LLMEndpoint` base URL + `model_capabilities` tags matter to the router — MLX is not required. |

The router keys entirely off the `model_capabilities` tags and endpoint health, so
you can mix backends and topologies freely as long as each capability tag in the
chains above resolves to at least one enabled endpoint.
