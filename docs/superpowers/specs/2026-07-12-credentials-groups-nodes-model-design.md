# Credentials · Groups · Nodes — normalized credential model

**Status:** design · **Date:** 2026-07-12 · **Owner:** kri

## Problem

Credentials are currently attached in two places — `Group.credential_id` **and**
`Node.credential_id` — and the node import flow *also* asks for inline SSH
username/password/key, which silently creates a per-node "shadow" credential. The
result is confusing and error-prone: a user imported two nodes into group `mac`
with no inline creds, expecting the group to supply them, but the group had **no
credential attached**, so the resolver's group tier (`Group.credential_id IS NOT
NULL`) skipped it and the bootstrap had no usable login. Nothing surfaced the gap.

## Goal

One obvious place for credentials. A node's login is always: **node → group →
credential**. No inline creds at import, no per-node overrides, no credential-less
bootstraps.

## Model (approved)

Three first-class entities, two associations:

```
Credential   (id, name, username, secret_enc, kind)     -- reusable secret
Group        (id, name)                                  -- NO credential column
Node         (id, ...)                                   -- NO credential column
credential_groups (credential_id FK, group_id FK)        -- UNIQUE(group_id)
group_members     (group_id FK, node_id FK)              -- exists today
```

- **One credential per group**, enforced by `UNIQUE(group_id)` on
  `credential_groups`. A credential may cover **many** groups (reuse).
- Managed **credential-side**: the Credentials page shows "this credential covers
  groups X, Y, Z."
- A **group may have no credential** (org-only grouping); only credential-mapped
  groups can bootstrap.

### Invariants (enforced in the service layer)
1. A **Credential** must map to ≥1 group — cannot be created/saved with zero group
   mappings; removing its last mapping deletes the credential (or is blocked).
2. A **Node** must belong to ≥1 group — import and manual-add both require a group.

### Resolution (rewritten resolver)
`node → group_members → groups → credential_groups → credential → decrypt`.
A node in multiple groups picks the highest-priority group's credential
(`Group.credential_priority DESC, name ASC` — the existing tiebreak). Controller
key / global settings remain **last-resort only**. `Node.credential_id` and
`Group.credential_id` are removed entirely.

## Schema migration

1. New table `credential_groups(credential_id, group_id, UNIQUE(group_id))`.
2. **Backfill**: for every current `Group.credential_id`, insert a
   `credential_groups` row. For every `Node.credential_id` with no group covering
   it, create (or reuse) a single-node group named `node:<minion_id>` mapped to
   that credential, and add the node to it — preserving today's effective login.
3. Any node with **no group** after backfill → add to a new **"Unassigned"** group
   (no credential; it cannot bootstrap until moved — the correct safe default).
4. Drop `Group.credential_id` and `Node.credential_id`.

## API / UI changes

- **Credentials page** (first-class): list/create/edit/delete credentials; each
  credential's editor manages its **group mappings** (multi-select of groups;
  save blocked with 0 groups). Deleting a credential warns which groups lose creds.
- **Import modal**: remove the SSH username/password/key fields (done in spirit by
  #981's direction). Require **"Assign to group"**; the group carries the
  credential. Hard-gate auto-bootstrap: refuse with *"Group 'mac' has no
  credential — attach one"* when the chosen group's credential doesn't resolve.
- **Manual add node**: require a group.
- **Group editor**: drop the credential field; instead show (read-only) which
  credential covers this group, with a link to the Credentials page.

## Resolver / callers

`resolve_node_credentials_sync` (and async) rewritten to the new join. All callers
(bootstrap_node #965 SSH chain, provision, reconfigure_minions #977) already go
through the resolver, so they inherit the new model unchanged. `has_usable_secret`
and the credential-less error path stay.

## Phasing

1. **Schema + resolver** — `credential_groups` table, migration/backfill,
   resolver rewrite, drop the two FKs. Contract + resolution tests.
2. **Enforcement** — invariants at credential save (≥1 group) and node create
   (≥1 group); import/manual-add require a group; bootstrap hard-gate on a
   resolvable credential.
3. **UI** — Credentials page with group-mapping management; strip creds from the
   import modal + group editor; the "no credential" bootstrap gate message.

## Tests

- Resolution: node→group→credential; multi-group priority tiebreak; group with no
  credential → no secret; controller/global last-resort.
- Invariants: credential save rejected with 0 groups; node create rejected with 0
  groups; `UNIQUE(group_id)` prevents two credentials on one group.
- Migration: backfill preserves each node's pre-migration effective login;
  ungrouped nodes land in "Unassigned".
- Import: no inline SSH fields; auto-bootstrap blocked when the group's credential
  doesn't resolve.

## Non-goals

- Per-node credential overrides (removed by decision).
- Many-credentials-per-group (rejected — one per group, priority handles
  multi-group nodes).
- Auto-discovery node ingestion (no such silent path exists today; node creation
  is import + manual-add only).

## Related

- Supersedes the inline-credential path in `#981` (import as-master) and the
  #703/#748 credential-store work (keeps the first-class Credential, drops the
  embedded FKs).
