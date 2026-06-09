# kri Fleet Platform — Project Rules

## Pre-Dispatch Research — Non-Negotiable

**Before dispatching any agent that touches existing code, complete this checklist. No exceptions.**

```
[ ] graphify query run → output pasted into agent prompt
[ ] Exact file paths identified (not "somewhere in ansible.py")
[ ] Exact line ranges read with offset/limit → code snippet embedded in prompt
[ ] Model assigned: haiku if ≤3 files + exact snippets; sonnet if ≥4 files or integration judgment
[ ] Test scope explicit: "run only tests/unit/test_<your_file>.py — full suite runs at merge time"
```

**Why this matters:** Each "find the function" loop an agent does costs ~5k tokens and ~30s. With 7 agents, that's 35k tokens of pure discovery waste. The parent session already has warm context — research here costs almost nothing.

**How to do the research:**

```bash
# 1. Query the graph (required — clears the dispatch hook sentinel)
graphify query "the subsystem being changed"

# 2. Get exact line numbers
grep -n "def function_name\|class ClassName" fleet_platform/path/to/file.py

# 3. Read only the relevant section (not the whole file)
# Use Read tool with offset=<start_line> limit=<n_lines>
```

Then paste the output directly into the agent prompt as a code block labelled `## Current code`.

---

## Agent Test Scope — Non-Negotiable

**Agents run only their own new test file. The full suite runs once at merge time.**

In every agent prompt, write explicitly:
```
Run: pytest tests/unit/test_<your_file>.py -q
Do NOT run the full pytest tests/unit/ suite — that is the merge gate, not the agent gate.
```

**Why:** Running 1639 tests in every agent costs ~3-5k tokens of output per agent. Over 7 agents that's 35k wasted tokens and ~7 minutes of extra wall-clock time.

---

## Model Selection — Decision Tree

```
Fix touches 1–3 files AND you have exact old_string/new_string in the prompt?
  → haiku

Fix touches 4+ files OR requires integration judgment across modules?
  → sonnet

Architecture design, broad codebase review, debugging non-obvious failure?
  → sonnet

End-of-branch holistic review before merge?
  → opus
```

**Never omit the model parameter.** Default inherits the parent model (Sonnet), which is always overpowered for mechanical fixes.

---

## graphify — Freshness Rules

The global hook auto-refreshes `graphify-out/graph.json` in the background whenever a new commit lands. You do not need to manually refresh.

What you DO need to do each session: run at least one `graphify query` before dispatching any agent. This ensures you have actual graph output to paste into prompts — not just a fresh graph you never read.

```bash
# At the start of any session involving agent dispatch:
graphify query "overview of the area you're working in"
```

---

## Unified CLI

All operations go through `scripts/kri` (no extension). Never call `kubectl`, `docker`, `helm` directly for routine tasks.

```bash
scripts/kri build          # build images
scripts/kri deploy         # deploy to k8s
scripts/kri test unit      # run unit tests
scripts/kri test report    # print test-reports/ summary table
scripts/kri logs backend   # tail API pod logs
```

---

## Commit Ordering for Parallel PRs

VERSION auto-bumps on every commit via pre-commit hook. When merging parallel branches sequentially:

1. Merge first PR → note the new VERSION
2. Before merging next PR: update its branch with `gh api repos/hellodk/kri/pulls/<N>/update-branch --method PUT`
3. Wait for CI, then merge

Never merge two branches simultaneously — they will conflict on VERSION and `frontend/package.json`.
