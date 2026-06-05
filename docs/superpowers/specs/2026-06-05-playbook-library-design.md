# Playbook Library — Design Spec

**Date:** 2026-06-05
**Status:** Approved, ready for implementation planning

---

## Problem

Every discovered playbook from every configured source is shown to operators on the Playbooks page. With 3 repos × 20 playbooks each, the page becomes cluttered and unusable. Operators need a curated workspace; admins need control over what gets exposed.

---

## Design Goals

1. Admins curate a subset of discovered playbooks into an **enabled workspace** — only those appear on the Playbooks page.
2. Operators can **star** enabled playbooks as personal favorites — starred ones float to the top.
3. All curation actions are **audited** using the existing `audit()` helper.
4. The system handles source changes (deleted files) **gracefully** with auto-disable and expiring notifications.

---

## Two-Level Curation Model

| Level | Who | Scope | Where |
|-------|-----|-------|-------|
| **Enable** | Admin | Global — all operators see it | Settings → Playbook Library |
| **Favorite** | Any user | Personal — only that user sees the star | Playbooks page |

---

## Data Model

Two new tables, one Alembic migration.

### `playbook_catalog`

```sql
id            UUID PRIMARY KEY DEFAULT gen_random_uuid()
source_key    TEXT NOT NULL        -- git URL or local path (stable, not positional index)
source_label  TEXT NOT NULL        -- display name ("pulse", "salt-states")
filename      TEXT NOT NULL        -- "bootstrap_mac.yml", "roles/salt_minion"
entry_type    TEXT NOT NULL        -- "playbook" | "role"
enabled       BOOLEAN NOT NULL DEFAULT false
enabled_by    TEXT                 -- username who last enabled
enabled_at    TIMESTAMPTZ
auto_disabled_at TIMESTAMPTZ      -- set when sync removes the source file
created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
UNIQUE (source_key, filename)
```

`source_key` is the stable join point — git URL or local path. Not the positional index (which shifts when sources are reordered).

### `playbook_favorites`

```sql
id            UUID PRIMARY KEY DEFAULT gen_random_uuid()
user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE
catalog_id    UUID NOT NULL REFERENCES playbook_catalog(id) ON DELETE CASCADE
created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
UNIQUE (user_id, catalog_id)
```

---

## API

### Modified endpoint

```
GET /api/v1/playbooks/list
  Returns only enabled catalog entries (enabled=true).
  Each entry includes two new fields:
    catalog_id: UUID
    is_favorite: bool  (true if current user has starred it)
  Returns [] when nothing is enabled — not an error.
```

### New endpoints

```
GET /api/v1/playbooks/library
  Returns all discovered playbooks from all sources.
  Each entry annotated with: enabled (bool), catalog_id (UUID|null).

POST /api/v1/playbooks/library/enable
  Body: { source_key, source_label, filename, entry_type }
  Upserts a catalog row with enabled=true.
  Requires: admin role.
  Audit: playbook.enable

POST /api/v1/playbooks/library/disable
  Body: { catalog_id }
  Sets enabled=false. Row is kept (preserves history).
  Requires: admin role.
  Audit: playbook.disable

POST /api/v1/playbooks/library/enable-source
  Body: { source_key }
  Bulk-enables all currently discovered playbooks from that source.
  Requires: admin role.
  Audit: playbook.enable_source  (new_value includes count)

POST /api/v1/playbooks/favorites/{catalog_id}
  Adds a favorite for the authenticated user.
  Available to all authenticated users.

DELETE /api/v1/playbooks/favorites/{catalog_id}
  Removes the favorite.
  Available to all authenticated users.
```

---

## Sync Behaviour — Auto-Disable on Missing Files

Runs inside the existing `sync_all_git_sources` Celery task after each git pull.

**Steps:**
1. Re-run `discover_all()` on the synced source directory.
2. Collect the set of discovered filenames for that source.
3. Query `playbook_catalog` for `enabled=true` rows with that `source_key`.
4. Any catalog row whose `filename` is no longer discovered:
   - Set `enabled=false`, `auto_disabled_at=now()`.
   - Create a notification entry:
     ```
     type:       "playbook_auto_disabled"
     message:    "'Bootstrap Mac Mini' was disabled — removed from pulse"
     expires_at: now() + PLAYBOOK_NOTIFICATION_TTL
     ```
   - Audit: `playbook.auto_disable` with `actor="system"`.

**Notification TTL:** Configurable via platform settings (`PLAYBOOK_NOTIFICATION_TTL`), default 7 days.

**Surfacing in the UI:** No separate notification model is needed. The Library tab queries `audit_events` for `action="playbook.auto_disable"` events within the TTL window on page load and shows a dismissible banner if any exist. The banner lists the affected playbook names and the source they were removed from.

**Important:** Auto-disable only fires on an explicit sync (button or scheduled). Never on a normal page load — a temporary network blip will not wipe the enabled list.

---

## Audit Coverage

All write operations use the existing `audit()` helper (`fleet_platform/core/audit.py`). Sensitive fields are scrubbed automatically by `_scrub()`.

| Action | Actor | resource_type | Notes |
|--------|-------|---------------|-------|
| `playbook.enable` | username | `playbook_catalog` | old: `{enabled:false}`, new: `{enabled:true, filename, source}` |
| `playbook.disable` | username | `playbook_catalog` | old: `{enabled:true}`, new: `{enabled:false}` |
| `playbook.auto_disable` | `system` | `playbook_catalog` | new: `{enabled:false, reason:"source file removed"}` |
| `playbook.enable_source` | username | `playbook_source` | new: `{source_key, count}` |

Favorites are personal UI preferences — not audited.

---

## Frontend Changes

### PlaybooksPage (`frontend/src/pages/PlaybooksPage.tsx`)

- **Favorites section** — amber tint, `★ Favorites` header. Renders only when the user has at least one favorite. Each row has a filled amber ★. Same Run button.
- **All Enabled section** — below favorites. Every row has an outlined gray ☆ that fills on click (calls favorites API).
- **Stat cards** — "Playbooks" card shows `X enabled` count. A new "Favorites" card replaces the current standalone Roles card; roles count moves into the All Enabled section label.
- **Empty states** — two distinct variants:

  **No sources configured:**
  > 🔌 No playbook sources configured
  > Add a git repo or local directory under Settings → Sources, then enable playbooks from the library.
  > [Go to Sources →]

  **Sources exist but nothing enabled:**
  > 📚 No playbooks enabled yet
  > Playbooks must be enabled from the library before operators can run them.
  > Administrators can manage the library under Settings → Playbook Library.
  > [Browse Library →]

### Settings — Playbook Library tab (`frontend/src/pages/PlaybookLibraryTab.tsx`)

- New tab added after "Advanced" in the Settings tab bar. Playbook Sources already live in the Advanced tab — Playbook Library is its logical companion.
- Tab order becomes: General · Bootstrap · Remote Access · Integrations · Advanced · **Playbook Library** · LLM · Notifications
- Header: `"60 discovered across 3 sources · 12 enabled"`.
- Search bar + filter chips: **All / Enabled / Disabled**.
- Notification banner at top when the last sync auto-disabled anything — dismissible, self-clears after TTL.
- Per source: **collapsible accordion** (closed by default).
  - Header: source label, type badge (`git`/`local`), `X/Y enabled`, **Enable All** button.
  - Per playbook row: toggle switch, name, type badge, description.
  - Auto-disabled entries show amber `⚠ removed from source` badge.

### New API client

`frontend/src/api/playbookLibrary.ts` — all library and favorites calls.

`frontend/src/api/playbooks.ts` — `PlaybookEntry` type gains:
```ts
catalog_id?: string
is_favorite?: boolean
```

---

## First-Deploy Behaviour

The catalog starts **empty**. On first deploy, the Playbooks page shows the "No playbooks enabled yet" empty state. An admin must open Settings → Playbook Library and enable playbooks before operators can run anything.

This is intentional — curation is explicit, not automatic.

---

## Migration

One new Alembic migration:
- Creates `playbook_catalog` table with indexes on `(source_key, filename)` and `(enabled)`.
- Creates `playbook_favorites` table with index on `(user_id, catalog_id)`.
- No data seeding — catalog starts empty by design.

---

## Out of Scope

- Per-user enabled lists (global only)
- Playbook ordering / manual sort within the workspace
- Audit log for favorite actions
- Auto-enable on source add (admin must enable manually)
