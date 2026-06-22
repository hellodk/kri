# MLX Local Cluster — Operator Runbook (#712)

Serves the agent's planner / coder / worker / embed tiers from the 18× M4 mini
fleet as OpenAI-compatible endpoints, routed by capability tag.

## Tiers

| Tier   | Model (4-bit MLX)                         | Minions      | Port | max_concurrent |
|--------|-------------------------------------------|--------------|------|----------------|
| Planner| `Qwen2.5-14B-Instruct-4bit`               | mm1, mm2     | 8080 | 1              |
| Coder  | `Qwen2.5-Coder-14B-Instruct-4bit`         | mm3–mm6      | 8080 | 1              |
| Worker | `Qwen2.5-7B-Instruct-4bit`                | mm7–mm16     | 8080 | 2              |
| Embed  | `bge-m3-4bit`                             | mm17, mm18   | 8081 | 4              |

16 GB is tight for a 14B planner — keep `max_concurrent: 1`, the 8K session cap,
and the hard `MAX_ITERATIONS=6` agent bound. The embed sidecar runs on a worker
subset, never on planners.

## Roll out

```bash
# 1. Stage pillar + state tops (one-time)
cp salt/pillar/top.sls.example salt/pillar/top.sls
cp salt/states/top.sls.example salt/states/top.sls

# 2. Apply serving state per tier (canary first, then the rest)
salt 'mm1' state.apply ml.mlx_serve            # planner canary
salt 'mm3' state.apply ml.mlx_serve            # coder canary
salt 'mm7' state.apply ml.mlx_serve            # worker canary

# 3. Benchmark the canaries against the Phase-C gates
python scripts/mlx_bench.py --base-url http://mm1:8080/v1 --model qwen2.5-14b --tier planner --runs 20
python scripts/mlx_bench.py --base-url http://mm3:8080/v1 --model qwen2.5-coder-14b --tier coder --runs 20

# 4. If gates pass, roll out to all 18
salt 'mm*' state.apply ml.mlx_serve
```

## Register endpoints in kri

For each serving minion, create an `LLMEndpoint` (Settings → LLM) pointing at
`http://<minion>:<port>/v1` and set **model_capabilities** to the tier tag so the
router (`fleet_platform/services/tier_router.py`) selects it:

| Tier   | `model_capabilities` |
|--------|----------------------|
| Planner| `planner`            |
| Coder  | `coder_yaml,coder`   |
| Worker | `fast_summarize,worker` |
| Embed  | `embed` (also set `LLM_EMBED_BASE_URL`) |

The agent route auto-selects a `planner`-tier endpoint when no `endpoint_id` is
given; the admin-gated cloud fallback fires only for admin sessions and only when
every local tier is unhealthy.

## Health & routing

- `GET /api/v1/agent/tiers` — live snapshot (endpoints, health, in-flight load).
- A planner call failure trips a 60 s health cooldown; the router steers new
  sessions to the next-least-loaded healthy endpoint, degrading down the chain
  (`planner → general`), ending at the optional cloud endpoint for admins.

## Gates (Phase C done-when)

- ≥ 95% of queries served locally
- p95 first-token ≤ 2.5 s on the local planner
- $0 token cost

## Failover smoke test

```bash
# Take a planner offline; confirm the router fails over to the other planner.
salt 'mm1' service.stop ai.kri.mlx.planner
# new agent runs should route to mm2 (or general); GET /agent/tiers shows mm1 unhealthy
```
