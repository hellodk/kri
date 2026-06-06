# ARCH-001 · Three-repo split — kri / pulse / hydra

> **Status**: DRAFT for discussion · 2026-06-05
> **Author**: principal-architect review
> **Decision deadline**: open

## TL;DR

Today, **kri**, **pulse**, and **hydra** each carry parallel implementations of the same infrastructure: fleet bootstrap, monitoring stacks, secrets, Ansible runners, CI. This is the source of every "why don't they agree" issue you'll hit at scale.

Reframe as three layers:

| Layer | Repo | Owns |
|---|---|---|
| **Platform** | **kri** | nodes, identity, secrets, the shared monitoring stack, the runner that executes configs |
| **Workload — CI/CD** | **pulse** | Jenkins + iOS/Mac build pipelines, agent specifications, build optimisation |
| **Workload — Inference** | **hydra** | LLM engines, Modelfiles, benchmarks, inference-specific dashboards |

**kri is the platform. pulse and hydra are tenants.** Today's redundancy comes from each tenant carrying its own platform pieces. The fix is to consolidate platform pieces into kri and reduce pulse/hydra to "workload-only" content packages.

## Non-goals

- Not a single-repo merge. Three repos with clear contracts beats one monorepo with implicit ones.
- Not a rewrite. Existing code moves files, doesn't get re-engineered.
- Not a Kubernetes-vs-Salt war. Both stay; kri runs both.
- Not a vendor lock-in (Jenkins, Ansible, Salt, kube-prometheus-stack are all swappable; kri abstracts over them).

## Redundancies + placement decisions

Each row lists a duplicated concern and where it should live after this proposal.

| # | Duplicated today | Lands in | Rationale |
|---|---|---|---|
| 1 | Apple Silicon hardware exporter (Go + IOKit). Today in `hydra/apple-silicon-monitoring/apple-silicon-exporter/` | **kri** | The exporter measures the *node*, not the workload. kri provisions the node; kri ships its telemetry. Workload-specific metrics (`llm_*`, `mlx_*`, `jenkins_*`) stay in their workload repo. |
| 2 | Prometheus + Grafana + Alertmanager + OTel gateway. Today hydra builds its own; pulse has Jenkins-side metrics; kri has the canonical fleet stack | **kri** (one stack per cluster) | Tenants become *publishers*: ServiceMonitors, PrometheusRules, dashboard ConfigMaps with the sidecar label. The cylon bring-up already proved this — reusing the existing kube-prometheus-stack instead of building a parallel one. Generalise. |
| 3 | Node onboarding / bootstrap. `hydra/scripts/add-cluster-node.py`, `pulse/ansible/setup-ios-agent.yml`, kri's "one-click bootstrap" UI | **kri** | kri is literally designed for this. The bespoke scripts in hydra and pulse reinvent it. After the move, hydra and pulse register *node profiles* (groups, roles, labels) that kri's UI consumes. |
| 4 | Ansible / Salt runner execution. kri runs both as a service; hydra invokes `ansible-playbook` from CLI; pulse runs standalone | **kri runs them; hydra + pulse author the content** | kri's drift detection depends on being the runner. Multiple uncoordinated runners create the drift it's supposed to detect. Workload repos become libraries of roles/states. |
| 5 | Tailscale / network ACL setup. `pulse/ansible/setup-tailscale-acl.yml`; hydra touches it; kri has fleet secrets | **kri** | Network policy is a platform concern. (Aside: hydra has explicitly opted out of Tailscale; consolidating to kri lets us choose one VPN-or-LAN model once.) |
| 6 | Secrets store. kri has role-scoped secrets; hydra has gitignored `hosts.yml`; pulse has Tailscale auth keys | **kri** | Tenants pull from kri's secret API at deploy time. Three private-data conventions across three repos is how leaks happen. |
| 7 | Grafana dashboards. hydra has 3; pulse has Jenkins dashboards; kri has fleet dashboards | **Repo-of-record stays per workload; runtime instance is kri's Grafana** | This is the pattern hydra's PR #19 already adopted: `grafana_dashboard: "1"` ConfigMap label, sidecar discovery. Apply across the board. |
| 8 | LaunchDaemon / systemd unit creation. kri's "process & service manager" does this generically; hydra writes specific plists; pulse writes specific units | **Workloads define the *spec*; kri operates it** | Hydra ships `templates/com.hydra.mlx.plist.j2` as content. kri installs and supervises it with RBAC + audit logs. |
| 9 | CI/CD pipelines. pulse runs Jenkins-on-k8s; hydra has GitHub Actions; kri has its own GitHub Actions | **pulse owns the cross-repo pipeline** | One CI system. Each repo keeps a 10-line webhook trigger that fires a pulse Jenkins job. |
| 10 | OTel agent on each Mac. hydra rolling this out (`otel-mac-agent`); pulse needs the same; kri may want drift telemetry | **kri owns the agent role; workloads contribute scrape configs** | One agent per host, many publishers. |

## What stays where (no migration needed)

- **kri**: drift detection, RBAC, SSH/VNC, secrets API — kri's value proposition. Untouched.
- **pulse**: `optimize_build_mac.sh`, iOS build pipeline, semgrep/SonarQube/JFrog integration, ephemeral-disk cleanup — pure CI primitives.
- **hydra**: `benchmarks/llm_bench.py` (multi-provider drivers), Modelfiles, LiteLLM config, vLLM/MLX/exo/AirLLM/BitNet engine integration, the LLM-specific exporter (`mlx_runtime_exporter`), the LLM-specific proxy (`llm-metrics-proxy`).

## The architectural rule

> **Promote anything that touches "the Mac" to kri. Demote anything that touches "the workload" to its tenant repo.**

If you can't quickly answer "kri, pulse, or hydra?" for a piece of code, apply the rule:

1. Does it identify, configure, or operate a *node*? → kri
2. Does it generate a build artifact or run tests? → pulse
3. Does it serve an LLM token or measure inference latency? → hydra
4. None of the above? → still kri (platform plumbing)

## Migration path

Ordered by smallest blast radius first. Each step is independently reversible.

| Step | Effort | Risk | Blocks |
|---|---|---|---|
| **1. Apple Silicon exporter → kri** | 1 day | Low — image registry change only | hydra needs to update its scrape config (already trivial in the push-pivot world: kri's Grafana scrapes via SM). |
| **2. Cylon becomes kri's reference cluster** | 2 days | Medium — touches live observability | pulse and hydra publish dashboards/SMs as ConfigMaps. kri runs the only kube-prom-stack. |
| **3. pulse Jenkins migrates to kri-provisioned Mac agents** | 1 week | Medium — touches CI | Bootstrap each Mac via kri UI; pulse defines the agent role. |
| **4. hydra `ansible/roles/{llm-*, otel-mac-agent}` → kri's role registry** | 2 weeks | Medium — touches deploy automation | kri's UI gains the LLM role catalogue. Hydra repo shrinks to LLM workload definition only. |
| **5. CI consolidation** | ongoing | Low | Each repo's GitHub Actions become 10-line Jenkins triggers. |

End state: **kri grows by ~30% (absorbing platform code), hydra shrinks by ~40%, pulse shrinks by ~30%**. Maintenance surface drops disproportionately because the deduplicated code stops drifting.

## Trade-offs worth naming

- **kri becomes a single point of failure.** Mitigated by treating kri itself as workload-on-cluster (it can be HA via standard Kubernetes patterns) and by keeping the per-Mac agents capable of running headless when kri is down.
- **kri becomes a release-cadence bottleneck.** When platform features land slowly, workload teams feel it. Counter-pattern: kri exposes stable APIs and the tenants pin versions.
- **Workload repos become "less self-contained."** A new contributor to hydra can't run the whole stack without kri. Document the standalone dev-mode path explicitly (a `docker-compose.dev.yml` in hydra that brings up a minimal local Prom + Grafana).
- **The split assumes one cluster running kri**. Multi-cluster (e.g. a dev kri + prod kri) is a follow-up — kri's API needs to know about cluster scopes.

## Open questions for discussion

1. **Should kri ship its own Grafana / Prometheus, or wrap an existing kube-prometheus-stack release?** Wrapping is faster; shipping is more controllable. Suggest: wrap for now (hydra's cylon already proves the pattern), revisit at the v1 line.
2. **What's the contract for "role content packages" that hydra/pulse hand off to kri?** OCI artifact? Git submodule? Helm chart? Suggest: OCI artifact via ghcr.io — versioned, signed, immutable.
3. **Do pulse's Jenkins jobs need access to kri's secrets API at build time?** Yes for iOS provisioning profile pulls. Define the auth boundary now — Jenkins agent token → kri secret-API scope.
4. **Drift detection coverage** — should kri detect drift in `apple-silicon-exporter.plist` (hydra-owned content)? Suggest: yes, but baselines come from hydra; kri scores them.
5. **Naming / namespacing** — should hydra's roles be `kri-roles/llm-mlx` or `hydra-roles/llm-mlx` once they live in kri's registry? Suggest: keep the workload prefix (`hydra-llm-mlx`) so origin is visible.

## Concrete next decisions

| Decision | Owner | When |
|---|---|---|
| Accept / reject the split as described | platform team | this week |
| Pick the role-content packaging mechanism | platform team | within 2 weeks |
| Land step 1 (exporter move) as the validation | one engineer | 1 day after acceptance |
| Document the kri ↔ workload-repo API surface | architecture | 1 month |

## Appendix — references

- `hydra/docs/SAVEPOINT-2026-06-05.md` — current state of hydra's monitoring overlay (live on cylon)
- `hydra/docs/push-based-monitoring-architecture.md` — why hydra pivoted to push (validates the "one stack" point for this proposal)
- `hydra/docs/cross-repo-knowledge.html` — interactive D3 of merged kri+pulse+hydra graphify graph; 142 cross-repo bridges visible
- `kri/README.md` — kri's existing feature list (everything in the platform-owns column is already there)

---

**To leave a comment, just edit this file inline and push a commit; or use the PR review thread.**
