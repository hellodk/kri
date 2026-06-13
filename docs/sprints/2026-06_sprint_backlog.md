# Sprint Backlog — 2026-06

Cross-cutting sprint covering deployment, ops, product, and architecture
dimensions. Generated from a four-axis audit (deployment / ops / product /
architecture) with a `next_sprint` time horizon. All 14 items shipped in
this sprint at `VERSION` 0.1.469.

## Summary

| Dim | ID | Item | SP | Status |
|-----|----|------|---:|--------|
| Blocker | B1 | k8s health probe path mismatch (`/healthz` → `/health/ready`) | 1 | ✅ |
| Blocker | B2 | SSH connection cache HA mitigation (sessionAffinity) + Redis follow-up | 3 | ✅ |
| Deploy | D1 | nginx hardcoded resolver → envsubst template (Podman compat) | 2 | ✅ |
| Deploy | D2 | launchd plists + Mac mini native install README | 3 | ✅ |
| Deploy | D3 | Kustomize base — Namespace + imagePullSecret + image-tag transformer | 3 | ✅ |
| Deploy | D4 | k8s SSH key Secret + worker volume mounts | 2 | ✅ |
| Ops | O1 | Wire real OpenTelemetry tracing (replace random trace_id) | 5 | ✅ |
| Ops | O2 | `terminationGracePeriodSeconds` + `preStop` on worker-ansible | 1 | ✅ |
| Ops | O3 | Encrypt + offsite-sync `pg_backup` output (age + rclone) | 2 | ✅ |
| Product | P1 | LLM streaming endpoint (SSE) + EventSource consumer | 5 | ✅ |
| Product | P2 | Salt `state.apply` dry-run (`test=True`) toggle | 2 | ✅ |
| Product | P3 | OS-aware baselines with `os_family` priority lookup | 3 | ✅ |
| Arch | A1 | NodeDetail tabs lazy-loaded + utility dedupe | 5 | ✅ |
| Arch | A2 | Integration + e2e Playwright jobs in CI | 1 | ✅ |
| | | **Total** | **38** | |

---

## Blockers

### B1 — k8s health probe path mismatch (1 SP)

**Problem.** `deploy/k8s/api-deployment.yaml` had `livenessProbe` and
`readinessProbe` pointing at `/healthz`, which doesn't exist on the
FastAPI app. Pods would CrashLoopBackOff on every k8s rollout.

**Fix.**
- API liveness probe → `/health`, readiness → `/health/ready`
  (`fleet_platform/api/routes/health.py` already serves both).
- Frontend nginx now serves a dedicated `location = /healthz` that returns
  `200 OK` independent of upstream — see `deploy/nginx.conf.template` and
  `deploy/nginx-tls.conf.template`.

### B2 — SSH connection cache is per-process (3 SP)

**Problem.** `fleet_platform/services/ssh_connection_cache.py` keeps
paramiko `SSHClient` sessions in a process-local dict. With 3 API
replicas behind a load-balanced k8s Service, a WebSSH session created on
pod A could be routed to pod B on the next request, dropping the shell.

**Short-term fix (this sprint).** Set `sessionAffinity: ClientIP` (3 h
timeout) on `deploy/k8s/api-service.yaml` so a client sticks to the same
pod for the lifetime of a typical SSH session.

**Long-term follow-up.** A Redis-backed session registry that lets any
pod adopt any session. Tracked in code via the comment block on
`ssh_connection_cache.py` — file a Linear ticket before the next sprint.

---

## Deployment

### D1 — nginx hardcoded resolver (2 SP)

**Problem.** `deploy/nginx.conf` had `resolver 127.0.0.11`, the Docker
embedded DNS address. On Podman (rootful: `10.88.0.1`, rootless:
`10.0.2.3`) and bare-metal it doesn't exist, so nginx fails to start.

**Fix.**
- Renamed `deploy/nginx.conf` → `deploy/nginx.conf.template` (and the TLS
  variant) with `resolver ${NGINX_RESOLVER}`.
- `deploy/Dockerfile.frontend` copies the template to
  `/etc/nginx/templates/default.conf.template` and sets
  `NGINX_ENVSUBST_FILTER='^NGINX_'` so only our placeholders are
  substituted.
- Default `NGINX_RESOLVER=127.0.0.11` keeps Docker users on the existing
  zero-config path.
- `deploy/.env.docker.example` documents the per-runtime values.

### D2 — launchd plists for Mac mini native (3 SP)

**Problem.** `deploy/systemd/` covers Linux but Mac mini deployments had
no native init unit equivalent.

**Fix.**
- `deploy/launchd/run.sh` — shell wrapper that sources env, finds `uv` in
  homebrew/cargo locations, and execs the right entrypoint per role.
- `deploy/launchd/com.kri.{api,worker,worker-ansible,beat}.plist` — one
  plist per service; worker-ansible has `ExitTimeOut` matching the
  Celery 35-min hard limit.
- `deploy/launchd/README.md` — install guide (sysadminctl service user,
  `launchctl bootstrap`, `newsyslog` for log rotation).

Linux `systemd` units were also touched: switched `ExecStart` to
`/usr/bin/env uv` and added `Environment=PATH` so the same units work on
hosts where `uv` is in `~/.local/bin` vs `/usr/local/bin`.

### D3 — Kustomize base (3 SP)

**Problem.** k8s manifests had no canonical apply order, no namespace
declaration, and image tags were hardcoded inline (`gitea.local/kri/...:0.1.415`).

**Fix.**
- `deploy/k8s/namespace.yaml` — declares the `kri` namespace.
- `deploy/k8s/kustomization.yaml` — Kustomize base with
  `namespace: kri`, declares all resources, parameterizes image tags via
  `images:`, and patches `imagePullSecrets: [regcred]` into every
  Deployment.
- `deploy/k8s/README.md` — quick-start (create regcred + kri-secrets,
  `kubectl apply -k deploy/k8s`).

### D4 — k8s SSH key Secret (2 SP)

**Problem.** Both worker deployments need an SSH keypair for Salt master
key listing and Ansible playbook runs but neither manifest mounted any.

**Fix.**
- `deploy/k8s/secret.yaml.template` documents the `kri-worker-ssh`
  Secret format and the keygen + `ssh-keyscan` steps.
- `worker-deployment.yaml` and `worker-ansible-deployment.yaml` now
  mount `/home/appuser/.ssh/{id_ed25519,id_ed25519.pub,known_hosts}`
  with file modes `0400`/`0444`.

---

## Operations

### O1 — Real OpenTelemetry tracing (5 SP)

**Problem.** `core/logging.py` was generating a random UUID4 per record
and labelling it `trace_id` — useless for distributed correlation.

**Fix.**
- New deps in `pyproject.toml`: `opentelemetry-sdk`,
  `opentelemetry-exporter-otlp-proto-grpc`, instrumenters for FastAPI,
  SQLAlchemy, Celery, httpx, Redis.
- New `fleet_platform/core/tracing.py` — gates on
  `OTEL_EXPORTER_OTLP_ENDPOINT`; idempotent and a no-op when unset.
- `core/logging.py::_add_trace_id` now uses
  `current_trace_id_hex()` from the active span; falls back to UUID4
  when no span is active or OTEL is unconfigured.
- API: `lifespan` calls `configure_tracing` + instruments SQLAlchemy /
  httpx / Redis; `create_app` instruments FastAPI.
- Workers: `worker_process_init.connect`'d
  `_init_worker_observability` does the same for Celery.
- `tests/unit/test_tracing_o1.py` covers the no-op path, idempotence,
  and the logging fallback.

### O2 — Worker-ansible grace + preStop (1 SP)

**Problem.** Ansible playbook tasks run for up to 35 minutes
(`task_time_limit=2100`) but k8s default `terminationGracePeriodSeconds`
is 30 s. A rolling deploy mid-job sent SIGKILL before Celery could
finish or re-queue.

**Fix.**
- `terminationGracePeriodSeconds: 3700` on `worker-ansible-deployment.yaml`
  (matches the hard limit + 100 s slack).
- `preStop` exec hook calls `celery control shutdown` so the worker
  drains in-flight tasks instead of dequeueing new ones during the
  grace window.

### O3 — Encrypted offsite backup (2 SP)

**Problem.** `pg_backup` wrote plain `.dump` files to a local volume
only. Loss of the host = loss of fleet history.

**Fix.**
- `deploy/docker-compose.yml::pg_backup` installs `age` + `rclone` at
  startup and reads three new env vars:
  - `BACKUP_AGE_RECIPIENT` — when set, every dump is age-encrypted
    before leaving the container.
  - `BACKUP_REMOTE` — rclone destination (e.g. `b2:bucket/kri/`).
  - `BACKUP_RCLONE_CONFIG` — verbatim rclone.conf contents written to
    `/root/.config/rclone/rclone.conf` at startup.
- `deploy/.env.docker.example` documents the keypair generation flow.
- `docs/OPS_RUNBOOK.md` — restore procedure rewritten to handle the
  encrypted format and added a DR-from-offsite section with target
  RPO 24 h / RTO 30 min.

---

## Product

### P1 — LLM streaming via SSE (5 SP)

**Problem.** `POST /api/v1/llm/query` blocked until the full response
arrived. For a 60-token reply on a small local model, that's 30+ s of
spinner.

**Fix.**
- `fleet_platform/services/llm_caller.py` adds `stream_anthropic` and
  `stream_openai_compat` async generators yielding `{type: 'delta'}`
  events.
- `POST /api/v1/llm/query/stream` — SSE endpoint that mirrors
  `submit_query` for context building, intent classification, and
  history budget; persists the query log on completion (or stream
  error) so the audit trail still works if the client disconnects.
- `frontend/src/api/llm.ts::streamQuery` consumes the stream via
  `fetch()` + `ReadableStream` (EventSource can't POST or send custom
  Authorization headers).
- `LLMAssistant.tsx` wired to the streaming path with cancel-via-abort.

### P2 — Salt `state.apply` dry-run (2 SP)

**Problem.** Operators couldn't preview what a state would change
before committing.

**Fix.**
- `ApplyRequest.test: bool = False` (`fleet_platform/api/routes/salt_ops.py`).
- `apply_salt_state(test_mode=...)` Celery task adds `test=True` to the
  Salt API kwarg and returns `status: ok_test` on success so the UI can
  distinguish a dry-run.
- Audit action splits into `salt.state.apply` vs `salt.state.apply.test`.
- `SaltOpsPage.tsx` — toggle in the apply dialog; result chip turns
  amber with a "Dry-run completed — no changes applied" banner.

### P3 — OS-aware baselines (3 SP)

**Problem.** A single global baseline forced macOS-only items
(`com.apple.screensharing` etc.) onto Linux nodes, generating noise in
drift reports.

**Fix.**
- New column `desired_state_baselines.os_family` (migration `050`).
- `services/baseline_loader.find_baseline_for_node` orders within each
  tier by `_os_priority`: exact-match `os_family` (priority 0) >
  OS-agnostic NULL (priority 1) > different OS (filtered out).
- `derive_os_family(node)` infers `Darwin` / `Linux` / `FreeBSD` /
  `Windows` from `macos_version` or `os_version` text.
- `BaselineCreate` / `BaselineUpdate` schemas accept `os_family`; PATCH
  with `""` clears the field back to OS-agnostic.
- `BaselinesPage.tsx` adds an OS-family selector to the create/edit
  modal and a small badge in the list view.

---

## Architecture

### A1 — NodeDetail lazy-loaded + utility dedupe (5 SP)

**Problem.** `frontend/src/pages/NodeDetail.tsx` is 2347 lines and
loaded eagerly in the main bundle on every page.

**Fix.**
- Existing `pages/nodeDetail/{utils,Sparkline,AiRecommendationPanel,IOSTabPanel}.tsx`
  extractions kept; `IOSTabPanel` is already `React.lazy()`'d for
  macOS-only nodes.
- New: every non-hub route in `frontend/src/App.tsx` is now
  `React.lazy()`-imported. The four AuthGuard landing surfaces
  (Overview, Compliance, Automation, Fleet) stay eager so login → first
  paint doesn't flash a spinner.
- `Layout.tsx` wraps `<Outlet />` in `<Suspense>` with a single shared
  spinner so each route doesn't need its own boundary.
- Bundle effect: NodeDetail.tsx, BaselinesPage.tsx, SBOMExplorer.tsx,
  and the Drift / Executions / Settings / Provisioning / Security
  pages now ship as separate chunks loaded on navigation.

**Follow-up.** Per-tab lazy split inside `NodeDetail.tsx` (Drift / SBOM /
Executions / Resources) is left for a follow-up PR — the route-level
chunking already delivers most of the benefit.

### A2 — Integration + e2e Playwright in CI (1 SP)

**Problem.** `tests/integration/` (43 files) and `tests/e2e/` (18
specs) only ran locally. Regressions could land on master without
catching httpx-level wiring or full-stack UI breaks.

**Fix.** `.github/workflows/ci.yml` gains two jobs:
- `integration-tests` — same Postgres + Redis services as `unit-tests`,
  runs `pytest tests/integration/`. Per-commit on every PR.
- `e2e-tests` — gated on the `e2e` PR label or master pushes only
  (Playwright runs cost ~10 min wall-clock). Boots the full
  docker-compose stack (`api worker pg_backup redis db frontend`),
  waits for `/api/v1/health`, runs `playwright test`. Uploads HTML
  report + stack logs as artifacts on failure.

---

## Validation checklist before deploying

1. `scripts/kri test unit && scripts/kri test integration`.
2. `cd frontend && pnpm run typecheck && pnpm run build` — confirms the
   route-level lazy refactor and `os_family` type changes compile.
3. Apply migration `050_baseline_os_family` on staging before pushing
   the new BaselinesPage UI.
4. Set `OTEL_EXPORTER_OTLP_ENDPOINT` on one staging pod and confirm
   spans flow before rolling to production.
5. Add the `e2e` label to the merge PR to exercise the new Playwright
   job once before disabling the gate (or keep the gate — the CI cycle
   stays fast).
6. After merging, file a Linear ticket for the long-term Redis-backed
   SSH session registry called out by the comment block in
   `services/ssh_connection_cache.py`.
