# kri Agent — Threat Model

Scope: the agentic subsystem (planner → executor → tools → approval → live).
Trust boundary: the LLM and any fleet-controlled string are **untrusted**.

## Assets

- The live fleet (minions, services, playbooks, pillars).
- The audit log (must be tamper-evident / append-only).
- Operator credentials and the cloud API key.

## Adversaries & mitigations

### 1. Prompt injection (via node fields, playbooks, tool results, user input)
- **Mitigation**: `prompt_safety.sanitize_untrusted` defangs code fences, model
  control tokens, tool-call tokens, and control/bidi/zero-width Unicode before any
  fleet string enters the prompt. Regression corpus of 60+ payloads asserts
  `not is_suspicious(sanitize_untrusted(x))` (100% pass). Tool results fed back
  are capped at 4 KB.
- **Residual**: a plain-language "please do X" injection can still *ask*; it
  cannot *act*, because every live action is gated by dry-run + human approval.

### 2. Confused deputy (agent acts with more authority than the operator)
- **Mitigation**: RBAC is re-checked at dispatch; tools carry `required_role`;
  the executor audits with `ctx.actor = operator email` (never "agent"); approved
  actions execute **as the original operator**.

### 3. Privilege escalation via tools / fuzzing
- **Mitigation**: strict JSON-schema validation (`additionalProperties: false`),
  per-tool input fuzz tests, a double-gated Salt allowlist (platform + agent
  read-only subset), and `write_live` tools that always require approval.

### 4. Destructive / control-plane actions
- **Mitigation**: `PROTECTED_TARGETS` (salt-minion, sshd, …) and `PROTECTED_NODES`
  (planner minis) are refused at propose *and* execute time; `process_kill` is
  forbidden; dangerous-pattern + forbidden-module scan rejects authored artifacts
  (`rm -rf /`, fork bomb, dd-to-device, `curl|sh`, TLS bypass).

### 5. Quarantine escape / promotion without review
- **Mitigation**: per-session 0700 dirs, path-traversal + symlink rejection,
  quotas, 24 h TTL. Promotion is admin-click-only and path-guarded. 0 artifacts
  reach live without a human action.

### 6. Runaway loops / resource exhaustion
- **Mitigation**: ≤ 6 iterations, ≤ 12 tool calls/turn, 6/min rate limit, 32 K
  input ceiling, client-disconnect check each iteration.

### 7. Unbounded cloud spend
- **Mitigation**: cloud is admin-gated, only on full local degradation, behind a
  daily spend cap circuit breaker.

### 8. Audit tampering
- **Mitigation**: **append-only by construction** — no tool to delete/modify audit
  rows exists (asserted in tests). Approvals/co-signs/promotions all leave human-
  attributed rows.

## Rollout trust-curve gates

Each stage advances only after **zero agent-caused incidents for 2 weeks**:
read-only → author-to-quarantine → single-node apply (approval) → multi-node
(co-sign) → promotion. Any agent-caused incident rolls back one stage.
