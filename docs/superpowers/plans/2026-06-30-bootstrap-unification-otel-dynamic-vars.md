# Bootstrap Role-Consolidation + Push-Telemetry + Dynamic Var Modal — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.
>
> **Design of record:** `docs/superpowers/specs/2026-06-26-ansible-role-consolidation-design.md` (#934). This plan EXECUTES that design, amended by the four decisions in "Amendments" below. Read #934 first for rationale; this doc is the build sequence, not a re-derivation.

**Goal:** Consolidate `playbooks/` into slim per-concern roles, make `bootstrap_node.yml` a thin orchestrator that installs salt-minion + node telemetry + a push OTEL agent + hardware exporter, and drive all tunables from a dynamic, type-aware kri bootstrap modal (and `vars_prompt` for CLI).

**Architecture:** Per #934 §4 — reusable installers become roles (`salt_minion`, `salt_master`, `otel_agent`, `hw_exporter`, `node_exporter` merged, `node_telemetry`); OS handled by `include_tasks: install_{macos,debian,redhat}.yml` gated `when:` inside each role; bootstrap-only glue stays inline (`tasks/host_prep.yml`). kri's existing `_kri_var_descriptions` discovery (`playbook_discovery.py`), enriched to a typed spec, powers a fully-dynamic type-aware bootstrap modal; collected values become extravars (kri worker) or `vars_prompt` (CLI).

**Tech Stack:** Ansible (ansible-runner, roles), FastAPI, SQLAlchemy, React/Vite + TanStack Query, Git LFS, otelcol-contrib, Salt 3007.14 onedir, kri mailer (`digest_svc._smtp_send`).

## Amendments to #934 (decided 2026-06-30)

1. **Linux salt-minion = onedir tarball** (air-gap, on-target `shasum -512`, extract `/opt/salt`, systemd) inside `salt_minion/install_{debian,redhat}.yml` — NOT apt/dnf.
2. **`otel_gateway_endpoint` has NO default — mandatory prompt.** Overrides #934's `100.89.50.27:30317`. Resolves the LAN-vs-Tailscale rule violation (nothing baked in). Required field in modal + required `vars_prompt`.
3. **Variable collection (#934 §6) is implemented via the typed `_kri_var_descriptions` discovery** → fully-dynamic, type-aware modal. The §6 substitution-contract table seeds the spec.
4. **Fully-dynamic modal, type-aware renderer.** Every field (incl. master selection via a `master_select` widget type) is rendered from the spec; no bespoke per-field code. New vars never require frontend changes.
5. **No `deploy_telemetry.yml`.** Telemetry rides the bootstrap; existing nodes get the new agents by **re-bootstrapping** (already supported; roles are idempotent). #934 §4's optional `deploy_telemetry.yml` is dropped. Migration = re-bootstrap.
6. **otelcol = `otelcol-contrib` first** (zero build effort); a slim custom-built collector is a later size optimization — the role/config is identical, only the vendored binary changes.
7. **dcgm-exporter runs as a container** on the single NVIDIA Linux node (NVIDIA's supported path — avoids vendoring `libdcgm`), scraped locally by `otel_agent`. apple-silicon (now) + AMD (when hardware lands, ~2mo) are vendored binaries.

## Global Constraints

- macOS bootstrap behaviour must remain equivalent through the refactor (roles produce the same on-host result); #694 pkgutil + checksum logic preserved in `salt_minion/install_macos.yml`.
- Salt pinned `3007.14`; Linux onedir must match. OTLP push tags every metric `node_id = salt.minion_id` (#934 §5).
- No baked endpoints/IPs in playbooks — all tunables in `group_vars/all.yml` (with `_kri_var_descriptions` typed entries) or mandatory-prompt. **`otel_gateway_endpoint` = no default.**
- LAN over Tailscale for any node→cluster traffic.
- Bundled binaries in `playbooks/files/` via Git LFS (`*.pkg`,`*.dmg`,`*.tar.gz` covered; add `*.tar.xz`).
- Completion email reuses `digest_svc._smtp_send`; recipients filtered to `DIGEST_RECIPIENTS`; secrets masked (#934 §7).
- Dynamic-var discovery applies to inbuilt playbooks only.
- Agent test scope: each task runs only its own new test file; full suite is the merge gate. Ansible roles: `ansible-playbook --syntax-check` + source-contract tests (relative paths via `pathlib`).

## Critical-path prerequisite — BINARY SOURCING (operator-gated)

These roles can be **written + unit/contract-tested** without binaries, but cannot **complete / field-verify** until the binaries are vendored (download + checksum + `git lfs add`). The parent/operator does this — agents must not fabricate binaries:
- `otelcol-contrib` — **darwin_arm64, linux_amd64** only (pin `otelcol_version`). No linux_arm64 (no ARM Linux nodes).
- `salt-3007.14-onedir-linux-x86_64.tar.xz` (+ `.sha512`) — **x86_64 only** (all Linux nodes are x86_64).
- hw_exporter: `apple-silicon-exporter` (arm64 macOS) — vendored now; **dcgm-exporter as a container** on the NVIDIA node (not a vendored binary) — set up now; AMD GPU exporter — detect-present, binary vendored when the AMD hardware lands (~2mo). Missing exporter → detect→log→skip (no hard fail).

---

## Phase 0 — Branch + binary manifest
- [ ] Confirm feature branch `feat/bootstrap-unification` (already created off master).
- [ ] Add `.gitattributes` rule `playbooks/files/*.tar.xz filter=lfs diff=lfs merge=lfs -text`; commit.
- [ ] Operator: vendor the binaries above into `playbooks/files/` via LFS (tracked separately; pins `otelcol_version`, exporter versions in `group_vars/all.yml`). Roles below reference them; field-verify gates on this.

## Phase 1 — `salt_minion` role (bootstrap calls only this)
**Files:** `playbooks/roles/salt_minion/tasks/{main,install_macos,install_debian,install_redhat,configure,service}.yml`; templates for systemd unit; `tests/unit/test_salt_minion_role.py`.
**Interfaces:** Input `salt_masters` (list), `minion_id`, `salt_master_pub_key?`. `main.yml` sets `_minion_os` then `include_tasks: install_{{ _minion_os }}.yml` + configure + service.
- macOS (`install_macos.yml`): move the current `bootstrap_node.yml` macOS pkg block verbatim (keep #694 pkgutil + `shasum -512`, no `lookup('file')`).
- Linux (`install_debian.yml`/`install_redhat.yml`): **onedir tarball** — resolve arch → get_url (override→Artifactory→bundle→official) → on-target `shasum -512` verify → `unarchive` to `/opt/salt` → symlink → systemd unit.
- `configure.yml`: write `/etc/salt/minion` (master list + `master_type: failover`, `random_master`, `OAEP-SHA1`), pre-seed master pubkey when supplied — moved from current inline.
- TDD: contract tests assert role structure, onedir (no apt/dnf salt install in Linux path), #694 preserved in macOS path. Commit per task file.

## Phase 2 — `node_telemetry` role
**Files:** `roles/node_telemetry/tasks/{main,install_macos,install_linux}.yml`; test.
- psutil (both OS: distro pkg on Linux, `pip --user` on macOS); `macmon`+`tart` (macOS, brew) via one `loop` (#934 §8). TDD contract tests. Commit.

## Phase 3 — `otel_agent` role (push telemetry)
**Files:** `roles/otel_agent/tasks/{main,install_macos,install_linux,service}.yml`; `templates/otelcol-config.yaml.j2`, `otelcol.plist.j2`, `otelcol.service.j2`; group_vars + `_kri_var_descriptions`; test.
- Config: receivers `hostmetrics` (cpu/mem/disk/net/fs) + `filelog` (`/var/log/salt/minion`) + `otlp` local + Prometheus `scrape` of local hw_exporter/node_exporter; processors `batch`,`resourcedetection`,`resource` (add `node_id={{ minion_id }}`, `fleet`); exporter `otlp` → `{{ otel_gateway_endpoint }}` (+ optional `otlp/fleet_platform`). No remote_write (no Victoria Metrics, #934 §11).
- `otel_gateway_endpoint`: **no default**; `_kri_var_descriptions` marks it `type: str, required: true`. Service install gated on endpoint set.
- TDD: config template references all receivers + the `{{ otel_gateway_endpoint }}` exporter; service unit per OS; group_vars has the var with NO default. Commit.

## Phase 4 — `hw_exporter` role (auto-detect accelerator)
**Files:** `roles/hw_exporter/tasks/{main,install_apple,install_nvidia,install_amd}.yml`; group_vars (binary names/versions); test.
- `gpu_provider` is a **detected fact** (#934 §4): Apple Silicon (Darwin+arm64)→apple-silicon-exporter (vendored binary); NVIDIA (`nvidia-smi`/`lspci` 10de)→**dcgm-exporter as a container** (load image, run, scrape locally); AMD (`rocm-smi`/`lspci` 1002)→AMD exporter (binary vendored when hardware lands); none→skip. Install only the matched one; missing artifact → log + skip (no hard fail).
- TDD: detection logic test (mock facts → expected provider); install task per provider; skip path asserted. Commit.

## Phase 5 — merge `node_exporter` role (optional, off)
**Files:** consolidate to the strong `node_exporter` role; delete `tasks/bootstrap/node_exporter_{linux,macos}.yml` + weak role body (#934 §4 delete list); test.
- Optional via `node_exporter_enabled | default(false)`; var schema unifies on `node_exporter_listen_address`/`_version` (map old `node_exporter_port`/`install_dir`). Commit.

## Phase 6 — thin `bootstrap_node.yml` + `host_prep.yml` + consolidate salt-master playbooks
**Files:** rewrite `bootstrap_node.yml` to the #934 §5 sketch (pre_tasks: arch/OS + accel detect + master-reachability gate; roles: salt_minion, node_telemetry, hw_exporter, otel_agent, node_exporter(when enabled); tasks: `import_tasks: tasks/host_prep.yml`; post_tasks: masked summary + email); create `tasks/host_prep.yml` (Xcode CLT, authorized_keys, VNC, grains-push — deduped, OS-conditional single grains `uri:`); fold `setup_salt_master.yml`/`install_salt_master_linux.yml`/`deploy_salt_master_mm1.yml` into ONE `install_salt_master.yml`. Delete the listed redundant files. **Do NOT create `deploy_telemetry.yml`** (Amendment 5 — migration is re-bootstrap). Test: `--syntax-check` + contract tests for the delete list + single grains task + no deploy_telemetry.yml.

## Phase 7 — completion email summary
**Files:** `bootstrap_node.yml` post_tasks (masked `set_fact` summary + debug); `fleet_platform/workers/ansible_tasks.py` (after run, send via `digest_svc._smtp_send`, recipients ∩ `DIGEST_RECIPIENTS`, secrets masked); test.
- TDD: summary masker redacts SSH/salt-api passwords + `node_token` + OTLP auth → `••••`; recipient filter rejects non-`DIGEST_RECIPIENTS`. Commit.

## Phase 8 — backend: typed var-spec discovery + endpoint + whitelisted extravars
**Files:** `services/playbook_discovery.py` (enrich `_kri_var_descriptions` → `VarSpec{name,default,description,type,options,sensitive,group,required}`, `type ∈ {str,int,bool,select,secret,master_select}`); `api/routes/ansible.py` new `GET /api/v1/ansible/bootstrap/vars`; `workers/ansible_tasks.py` `bootstrap_node(..., extra_vars: dict)` whitelisted to spec names via `_scrub_extravars`; tests.
- `master_select` type → renderer fetches masters from the masters API; mandatory-master gate enforced server-side (≥1, with manual-IP fallback per #934 §6).
- TDD: discovery returns typed specs (incl. `otel_gateway_endpoint` required, no default; a `master_select` var); endpoint returns them; whitelist drops unknown keys. Commit per task.

## Phase 9 — frontend: fully-dynamic type-aware modal
**Files:** `frontend/src/api/ansible.ts` (`bootstrapVars()`, `bootstrap(...,extraVars)`); `frontend/src/pages/BootstrapModal.tsx` (render fields from spec by `type`: int→number, bool→checkbox, select→dropdown, secret→SecretInput, master_select→existing-master picker w/ health badges + manual-IP fallback, else text; group by `group`; mandatory fields validated; only-changed-from-default sent). `tsc` clean.
- TDD: `tsc -b --noEmit` 0 errors; (no FE unit harness — verified by build + the backend contract). Commit.

## Self-Review
**Coverage vs #934:** roles (P1–5,§4) ✓ · thin orchestrator + host_prep + salt-master consolidation (P6,§4–5) ✓ · push OTEL (P3,§5) ✓ · hw_exporter auto-detect (P4) ✓ · node_exporter optional (P5) ✓ · variable collection UI+CLI (P8–9,§6) ✓ · completion email masked + filtered (P7,§7) ✓ · dedup (P6,§8) ✓. **Amendments:** onedir (P1) ✓ · no-default OTLP (P3) ✓ · discovery-driven §6 (P8) ✓ · fully-dynamic type-aware modal incl. master_select (P9) ✓.
**Type consistency:** `VarSpec` fields (P8) == `bootstrapVars()` shape (P9); `gpu_provider` detected fact name consistent P4/P6; `otel_gateway_endpoint` no-default across P3/P8/P9.
**Honest open items:** (1) binary sourcing (Phase 0) gates field-verification of P1/P3/P4 — GPU exporters the long pole. (2) Linux + GPU paths unproven on real hosts until one end-to-end run. (3) LFS footprint (otelcol ×3 + salt onedir ×2 + 3 exporters) — confirm budget. (4) otel-gateway must accept unauthenticated OTLP POST from fleet nodes (#934 §12.1 — smoke-test during P3).
