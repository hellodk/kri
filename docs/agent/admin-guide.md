# kri Agent — Admin Guide

Admin-only responsibilities: promotion, co-sign, the cloud fallback, and the
kill switches.

## Promotion (quarantine → live)

Authored artifacts live in quarantine and are **never** auto-promoted. Promotion
is an explicit admin action — `POST /api/v1/agent/artifacts/{session}/{file}/promote?target=<path>`
— not a registry tool the agent can call. The target must resolve inside an
allowed playbook root (path-traversal + symlink rejected) and every promotion is
audited with your email.

## Co-sign

Agent-proposed actions hitting **> 8 targets** (`PendingAction.CO_SIGN_THRESHOLD`)
require an admin co-sign in addition to the first approval. The co-signer must be
an admin **and** a different person than the first approver. Execution then runs
as the original operator.

## Cloud fallback

The local MLX cluster serves ~all traffic at $0. The admin-gated cloud endpoint
is used only when (a) the session is an admin's, (b) every local planner tier is
unhealthy, and (c) the **daily spend cap** is not exhausted
(`AGENT_CLOUD_DAILY_CAP_USD`, default $5). Monitor `GET /api/v1/agent/costs`.

## Tier health

`GET /api/v1/agent/tiers` shows which endpoints serve planner/coder/worker/embed,
their health, and in-flight load. A failed planner call trips a 60 s cooldown and
the router fails over automatically. See `docs/runbooks/mlx-cluster.md`.

## Kill switches

- Disable any tool by setting its `ToolSpec.enabled = False` (kill-switched tools
  are never offered to any role).
- Disable an endpoint in Settings → LLM to drop it from routing.
- Set `AGENT_CLOUD_DAILY_CAP_USD=0` to forbid cloud entirely.
- `AGENT_PROTECTED_NODES` extends the planner-self-deplane protection list.

## Configuration

| Env | Default | Purpose |
|-----|---------|---------|
| `AGENT_QUARANTINE_ROOT` | `/srv/kri/agent-quarantine` | quarantine fs root |
| `AGENT_PROTECTED_NODES` | `mm1,mm2` | nodes the agent may not deplane |
| `AGENT_CLOUD_DAILY_CAP_USD` | `5.0` | cloud spend circuit breaker |
| `AGENT_CLOUD_COST_PER_1K_USD` | `0.009` | blended cloud token price |
