# Runbook — Agent Incident Response

For suspected agent misbehavior: a bad change, a runaway session, prompt-injection
suspicion, or cloud overspend.

## 0. Immediate containment

```bash
# Stop all new agent runs (disable the planner tier endpoints in Settings → LLM,
# or set the cloud cap to zero to kill cloud fallback):
export AGENT_CLOUD_DAILY_CAP_USD=0   # then redeploy / restart API

# Kill switch a specific tool: set ToolSpec.enabled=False in agent/tools.py and
# redeploy — kill-switched tools are never offered to any role.
```

## 1. Triage — what did it do?

Every tool call and approval is in the audit log, attributed to a human:

```sql
-- Recent agent tool dispatches
SELECT created_at, actor, action, new_value
FROM audit_events
WHERE action LIKE 'agent.tool.%' OR action = 'agent.artifact.promote'
ORDER BY created_at DESC LIMIT 100;

-- Pending / executed live actions for a session
SELECT id, tool_name, status, requested_by, approved_by, co_signed_by, executed_at
FROM pending_actions
WHERE proposed_by_agent = true
ORDER BY created_at DESC LIMIT 50;
```

The agent session ties it together: `agent_sessions` + `llm_query_log.agent_session_id`.

## 2. Was it prompt injection?

- Pull the `initial_prompt` and the tool results for the session.
- Run suspect strings through `prompt_safety.is_suspicious`; if a *new* class
  slips through, add it to `tests/unit/test_injection_corpus_715.py` and harden
  `prompt_safety`.

## 3. Reverse a bad change

- Live changes went through dry-run + approval; the dry-run output is on the
  PendingAction (`dry_run_result`). Use it to scope the blast radius.
- Re-apply the previous known-good state/playbook (git history of the live tree).
- Promotions are auditable (`agent.artifact.promote`): revert the file in the
  playbook tree and re-promote the corrected version.

## 4. Planner failover (chaos / outage)

```bash
# Confirm tier health and current routing:
curl -s localhost:8000/api/v1/agent/tiers | jq

# Take a planner offline; router fails over to the other planner (60 s cooldown):
salt 'mm1' service.stop ai.kri.mlx.planner
# New sessions route to mm2; admins degrade to cloud only if the cap allows.
```

## 5. Cloud overspend

```bash
curl -s localhost:8000/api/v1/agent/costs | jq   # spend vs daily cap
```
If `capped: true`, cloud fallback is already refused. Lower
`AGENT_CLOUD_DAILY_CAP_USD` if needed.

## 6. Post-incident

- File the incident; if agent-caused, roll the rollout trust-curve back one stage
  (see threat-model.md).
- Add a regression test (injection string, fuzz case, or guard) so the same class
  cannot recur.
