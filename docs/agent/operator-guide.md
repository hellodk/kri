# kri Agent — Operator Guide

The agent turns a question ("why is mm7 degraded?") into a bounded sequence of
read-only tool calls, then — when you ask it to change something — proposes a
**dry-run + approval** action. It never changes the fleet on its own.

## Modes

- **Q&A** — single-shot question/answer over the fleet knowledge base.
- **Agent** — multi-step investigation with tools. Sub-views:
  - **Run** — the live step-by-step transcript (each tool call + result).
  - **Artifacts** — playbooks/states the agent authored into *quarantine*.
  - **Approvals** — live actions awaiting your approval / admin co-sign.

## What the agent can do without approval

Read-only tools only: list/inspect nodes, recent audit, read & search playbooks,
RAG search, embeddings, `test.ping`, a read-only Salt allowlist, and
`state.apply test=True` dry-runs. It can also **author** playbooks/states — but
only into quarantine, never the live tree.

## What requires approval

Any live change (`apply_salt_state`, `restart_service`, `set_pillar`,
`bootstrap_node`, `enable_node`):

1. The agent runs a **dry-run first** (gate enforced by the executor).
2. It **proposes** the action — this creates a Pending Action with the captured
   dry-run output.
3. You **approve** it in the Approvals panel. Actions hitting **> 8 targets**
   also need an **admin co-sign** (a different person).
4. On full approval the tool executes **as you** (the original operator) — the
   audit row names you, not the approver and not "the agent".

Approvals expire after **4 hours**.

## Bounds you can rely on

- ≤ 6 reasoning iterations and ≤ 12 tool calls per turn.
- Tool results fed back to the planner are capped at 4 KB.
- Quarantine quotas: 5 MB/session, 50 MB/user, 64 KB/artifact, 24 h TTL.
- Protected control-plane targets (salt-minion, sshd, …) and planner minis
  (mm1/mm2) can never be taken offline by the agent.

## Tips

- Be specific ("restart nginx on mm9", not "fix the web tier").
- Review the dry-run and the Monaco diff before approving.
- If a tool errors, the agent will tell you in plain text rather than loop.
