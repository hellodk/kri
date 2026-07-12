# Usable Master Promotion + Minion Re-pointing

**Status:** design · **Date:** 2026-07-12 · **Owner:** kri

## Problem

Promoting a node to a salt-master is currently useless: promotion only writes a
`SaltMaster` DB row (`unprovisioned`), and even once provisioned, **no existing
minions point at the new master**, so it has nothing to manage. Salt has no
master auto-discovery — a minion only knows the masters in its own `minion.conf`.

## Enabling facts (verified)

- **Multi-master already works.** `roles/salt_minion/templates/minion.conf.j2`
  renders `master:` as a list from `salt_masters` with `master_type: failover`,
  `random_master: True`. Passing N masters configures HA failover today.
- **Shared master keypair.** `deploy/salt-pki/master.pem`/`.pub` is copied onto
  every master the `salt_master` role provisions (`pki.yml`), and minions pin that
  one pubkey. So every kri-provisioned master is cryptographically interchangeable —
  adding a master to a minion needs **no new key trust on the minion side**; only
  the new master must accept the minion's key.
- **Install is playbook-only** (`install_salt_master.yml`); `provision_master`
  just streams it.

## Decisions (locked)

- **Additive / HA** — re-pointed minions get `[existing masters + new master]`.
- **Thin Ansible playbook** — a dedicated `reconfigure_minion_masters.yml` re-renders
  `minion.conf` + restarts, reusing the `salt_minion` role's configure/service tasks.
- **Phased C → B → A.**

## Design

### Phase C — minion re-point workflow (first; makes promotion useful)

- **Playbook** `playbooks/reconfigure_minion_masters.yml`: thin, `hosts: targets`,
  imports `common` then runs only the `salt_minion` `configure` + `service` tasks
  (via a tag/slim entrypoint) — re-renders `minion.conf` with the new `salt_masters`
  list and restarts salt-minion. No install/telemetry/exporter.
- **Backend**: a `reconfigure_minions` Celery task (mirrors `provision_master`:
  loads SSH creds via the FK chain from #965, `ansible_runner.run_async`, streams to
  LogPane) + route `POST /masters/{master_id}/attach-minions` taking node IDs.
  - Per selected minion, compute the **additive** list = `node's current masters ∪
    {this master}` (from the node→master relationship the `masters/{id}/minions`
    endpoint already uses).
  - After restart, **auto-accept** the minions' keys on the new master via the wheel
    API (`key.accept` scoped to the exact minion IDs — an explicit allow-list, never
    `-A`).
  - Update the node→master links in the DB so the UI reflects reality.
- **UI**: per-master **"Attach minions"** button on the Salt Masters tab → multi-select
  of fleet minions (default-selected = peers' minions) → streams the run in the LogPane.

### Phase B — promote auto-provisions

`promoteFromNode` currently stops at a DB row. On promote, immediately enqueue
`provision_master`, and on success surface the Phase-C "attach minions" step. Flow:
**promote → installs master → "which minions should also report here?" → re-point.**

### Phase A — bootstrap "as master" toggle

Add a toggle to `BootstrapModal`. When on, bootstrap runs `salt_minion` **and** the
`salt_master` role on the target (node becomes master+minion), then registers it as a
`SaltMaster` (`from-node` path) with `provision_status: provisioned`. Reuses B/C.

## Scaling boundary (documented, not built)

The Phase-C reconfigure over SSH/Ansible is fine for tens of Macs. At 1000s of
minions, switch the delivery to salt-native (push config from a live master via
`state.apply`, one pub-sub call). `random_master: True` already distributes minions
across masters, and kri's presence poller already unions `manage.up` across all
masters (#689).

## Non-goals (YAGNI)

- Automatic master decommission / rebalancing.
- Per-minion master lists beyond additive-union.
- Hot-hot multi-master (failover is correct for kri — one relay per minion, no
  duplicate ingest; kri unions presence across masters).

## Tests

- Playbook re-renders the master list **additively** (contract).
- Task computes `current ∪ {new}` correctly.
- Key auto-accept is scoped to the exact minion IDs (never bulk `-A`).
- Route authz (admin); UI multi-select maps 1:1 to node IDs.
- Phase B: promote enqueues provision; provision success surfaces attach step;
  failure leaves status `error`.
- Phase A: toggle drives the extravar; both roles run; SaltMaster row created +
  marked provisioned.

## Related

- Sibling spec: `2026-07-12-node-otel-metrics-push-design.md` (monitoring epic).
- Depends on the roles-refactor (Phases 1–3, merged) and #965 (FK credential chain).
