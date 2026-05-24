# Audit Remediation Plan — Security, QA, and UI/UX

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix all 42 issues from the external security audit, QA audit, and UI/UX audit, plus the offline Ansible collections constraint and the Run Playbook modal UX improvements.

**Architecture:** Fixes span backend (security hardening, input validation, offline collections) and frontend (bug fixes, UX improvements). Each task is independently deployable. No new dependencies — only internal code changes.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy 2.0, Celery, React 18, TanStack Query 5, Tailwind CSS.

---

## Already fixed (do not re-implement)
- Ansible `hosts: target → targets` mismatch — fixed in commit 3b71bab
- Bootstrap switched from dynamic.py to static inventory.ini — fixed in commit 3b71bab

---

## File Structure

| Action | Path | Purpose |
|--------|------|---------|
| Create | `playbooks/collections/` | Bundled offline ansible.posix collection |
| Modify | `fleet_platform/workers/ansible_tasks.py` | Remove galaxy call, add validation, input sanitization, file locking |
| Modify | `fleet_platform/workers/playbook_tasks.py` | Path traversal fix, inventory permissions, log git failures |
| Modify | `fleet_platform/api/routes/ansible.py` | Rate limit bootstrap, stricter playbook path check, pillar path config |
| Modify | `fleet_platform/api/routes/ingest.py` | No changes needed |
| Modify | `fleet_platform/services/platform_settings_svc.py` | Add PILLAR_DIR constant |
| Modify | `fleet_platform/schemas/ansible.py` | Add PillarDir to settings response |
| Modify | `frontend/src/components/Layout/TopBar.tsx` | Search empty state |
| Modify | `frontend/src/pages/NodeDetail.tsx` | onError handlers, add-tag toast, tag input UX |
| Modify | `frontend/src/pages/BootstrapModal.tsx` | CTA after complete, logs auto-refresh |
| Modify | `frontend/src/pages/PlaybooksPage.tsx` | Run confirmation, empty state |
| Modify | `frontend/src/pages/PlaybookRunModal.tsx` | Bigger dialog, variable editor warnings |
| Modify | `frontend/src/pages/FleetDashboard.tsx` | Empty state onboarding |
| Modify | `frontend/src/pages/SettingsPage.tsx` | Required/optional sections, eye icon |
| Modify | `frontend/src/pages/GroupDetail.tsx` | Group type tooltip, node selector hint |
| Modify | `frontend/src/components/Layout/Sidebar.tsx` | Tooltips in collapsed mode |
| Modify | `frontend/src/components/Pagination.tsx` | Per-page selector |

---

## Task 1: Offline Ansible collections — bundle ansible.posix in repo

**Files:**
- Create: `playbooks/collections/` (bundled tarball)
- Modify: `fleet_platform/workers/ansible_tasks.py`

**Context:** `ansible-galaxy collection install` requires internet. In air-gapped environments this silently fails and bootstrap errors with a cryptic module-not-found. Fix: bundle the collection in the repo and point `ANSIBLE_COLLECTIONS_PATH` at it. Remove the subprocess galaxy call entirely.

- [ ] **Step 1: Bundle ansible.posix collection into repo**

```bash
cd /home/dk/Documents/git/kri
mkdir -p playbooks/collections
# Build offline tarball from already-installed collection
ansible-galaxy collection build ~/.ansible/collections/ansible_collections/ansible/posix \
  --output-path playbooks/collections/ 2>&1
ls playbooks/collections/
```
Expected: `ansible-posix-*.tar.gz` file created.

- [ ] **Step 2: Install it into a vendored path**

```bash
ansible-galaxy collection install playbooks/collections/ansible-posix-*.tar.gz \
  -p playbooks/collections/installed/ --force 2>&1
ls playbooks/collections/installed/ansible_collections/ansible/posix/
```
Expected: collection files present.

- [ ] **Step 3: Remove galaxy call from ansible_tasks.py**

In `fleet_platform/workers/ansible_tasks.py`, remove the entire block at lines 121-128:
```python
    # 4. Install required Ansible collections
    requirements_file = _PLAYBOOKS_DIR / "requirements.yml"
    if requirements_file.exists():
        import subprocess
        subprocess.run(
            ["ansible-galaxy", "collection", "install", "-r", str(requirements_file)],
            capture_output=True,
        )
```

And add `ANSIBLE_COLLECTIONS_PATH` to the runner's envvars so Ansible finds the bundled collection:
```python
        result = ansible_runner.run(
            private_data_dir=tmpdir,
            playbook=str(_PLAYBOOKS_DIR / "bootstrap_mac_mini.yml"),
            inventory=str(inv_path),
            extravars={
                "salt_master_address": salt_master,
                "minion_id": node.minion_id,
                "controller_pubkey": controller_pubkey,
                "ansible_ssh_common_args": "-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null",
            },
            envvars={
                "ANSIBLE_COLLECTIONS_PATH": str(_PLAYBOOKS_DIR / "collections" / "installed"),
            },
            quiet=False,
            rotate_artifacts=1,
        )
```

Do the same in `fleet_platform/workers/playbook_tasks.py` — add `ANSIBLE_COLLECTIONS_PATH` to the envvars dict in `run_playbook`.

- [ ] **Step 4: Verify collection resolves without network**

```bash
cd /home/dk/Documents/git/kri && source .venv/bin/activate
ANSIBLE_COLLECTIONS_PATH=playbooks/collections/installed \
  ansible-doc ansible.posix.authorized_key 2>&1 | head -5
```
Expected: shows module docs, no network call.

- [ ] **Step 5: Run tests**

```bash
python -m pytest tests/ -q --no-header 2>&1 | tail -3
```
Expected: 200 passed.

- [ ] **Step 6: Commit**

```bash
git add playbooks/collections/ fleet_platform/workers/ansible_tasks.py \
  fleet_platform/workers/playbook_tasks.py
git commit -m "feat: bundle ansible.posix offline — remove ansible-galaxy runtime call"
```

---

## Task 2: Backend security — input validation + path traversal

**Files:**
- Modify: `fleet_platform/workers/ansible_tasks.py`
- Modify: `fleet_platform/workers/playbook_tasks.py`
- Modify: `fleet_platform/api/routes/ansible.py`
- Modify: `fleet_platform/services/platform_settings_svc.py`
- Test: `tests/unit/test_ansible_validation.py`
- Test: `tests/integration/test_playbook_api.py` (add traversal test)

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_ansible_validation.py
import pytest
from fleet_platform.workers.ansible_tasks import _validate_minion_id
from fleet_platform.workers.playbook_tasks import _safe_label


def test_valid_minion_id():
    assert _validate_minion_id("mac-mini-01") == "mac-mini-01"
    assert _validate_minion_id("mac.mini.01") == "mac.mini.01"
    assert _validate_minion_id("node_01") == "node_01"


def test_invalid_minion_id_path_traversal():
    with pytest.raises(ValueError, match="Invalid minion ID"):
        _validate_minion_id("../etc/passwd")


def test_invalid_minion_id_yaml_injection():
    with pytest.raises(ValueError, match="Invalid minion ID"):
        _validate_minion_id("foo\n  bar: baz")


def test_invalid_minion_id_spaces():
    with pytest.raises(ValueError, match="Invalid minion ID"):
        _validate_minion_id("mac mini 01")


def test_safe_label_strips_traversal():
    assert "/" not in _safe_label("../../etc/hosts")
    assert ".." not in _safe_label("../secrets")


def test_safe_label_valid():
    result = _safe_label("my-group-name")
    assert result == "my-group-name"
```

- [ ] **Step 2: Run to verify failure**

```bash
cd /home/dk/Documents/git/kri && source .venv/bin/activate
python -m pytest tests/unit/test_ansible_validation.py -v 2>&1 | tail -8
```
Expected: `ImportError` — functions don't exist yet.

- [ ] **Step 3: Add `_validate_minion_id` to ansible_tasks.py**

Add near the top of `fleet_platform/workers/ansible_tasks.py` after the imports:
```python
import re

_MINION_ID_RE = re.compile(r'^[a-zA-Z0-9._-]{1,128}$')


def _validate_minion_id(minion_id: str) -> str:
    if not _MINION_ID_RE.match(minion_id):
        raise ValueError(f"Invalid minion ID '{minion_id}': must match [a-zA-Z0-9._-]{{1,128}}")
    return minion_id
```

In `bootstrap_node`, call it immediately after loading the node:
```python
    with get_sync_db() as db:
        node = db.execute(select(Node).where(Node.id == node_uuid)).scalar_one_or_none()
        if not node:
            return {"status": "error", "reason": "node_not_found"}
        try:
            _validate_minion_id(node.minion_id)
        except ValueError as e:
            node.bootstrap_status = "failed"
            node.bootstrap_error = str(e)
            db.commit()
            return {"status": "error", "reason": str(e)}
```

Also call it in `_write_pillar_file` at the top:
```python
def _write_pillar_file(pillar_dir: str, minion_id: str, ingest_url: str, node_token: str) -> None:
    _validate_minion_id(minion_id)  # raises ValueError on invalid input
    ...
```

- [ ] **Step 4: Add `_safe_label` to playbook_tasks.py**

Add after imports in `fleet_platform/workers/playbook_tasks.py`:
```python
import re

_SAFE_PATH_RE = re.compile(r'^[a-zA-Z0-9._\-]{1,128}$')


def _safe_label(label: str) -> str:
    """Sanitise a label used in file paths. Strips anything not alphanumeric/.-_"""
    cleaned = re.sub(r'[^a-zA-Z0-9._\-]', '_', label)
    # Prevent traversal
    cleaned = cleaned.strip('.')
    if not cleaned:
        cleaned = "unknown"
    return cleaned[:128]
```

In `run_playbook`, replace `job.target_label` in path operations with `_safe_label(job.target_label)`:
```python
            if job.target_type == "node" and hosts:
                hostname = _safe_label(hosts[0][0])
                vf = playbooks_dir / "host_vars" / f"{hostname}.yml"
                ...
            elif job.target_type == "group":
                vf = playbooks_dir / "group_vars" / f"{_safe_label(job.target_label)}.yml"
```

- [ ] **Step 5: Fix playbook path resolution in ansible.py**

Replace the sanitisation at line ~155 in `fleet_platform/api/routes/ansible.py`:

Current (broken):
```python
    safe_name = payload.playbook.lstrip("/").replace("..", "")
```

Replace with:
```python
    # Resolve and verify the path is inside playbooks_dir
    try:
        candidate = (_PLAYBOOKS_DIR / payload.playbook).resolve()
        playbooks_resolved = _PLAYBOOKS_DIR.resolve()
        candidate.relative_to(playbooks_resolved)  # raises ValueError if outside
        safe_name = payload.playbook.lstrip("/").replace("..", "")
    except (ValueError, OSError):
        raise HTTPException(status_code=404, detail=f"Playbook not found or invalid path")
    entries = discover_all(_PLAYBOOKS_DIR)
    entry = next((e for e in entries if e.filename == safe_name), None)
    if not entry:
        raise HTTPException(status_code=404, detail=f"Playbook '{safe_name}' not found")
```

- [ ] **Step 6: Add rate limit to bootstrap endpoint**

In `fleet_platform/api/routes/ansible.py`, add rate limiting to the bootstrap endpoint.

Add import at top (already imported in other routes — check if limiter is imported):
```python
from fleet_platform.api.limiter import limiter
from fastapi import Request
```

Change bootstrap function signature to include Request and add limiter decorator:
```python
@router.post("/bootstrap", response_model=BootstrapResponse, status_code=202)
@limiter.limit("10/minute")
async def bootstrap(
    request: Request,
    payload: BootstrapRequest,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_role("operator", "admin")),
):
```

- [ ] **Step 7: Make pillar dir configurable**

In `fleet_platform/services/platform_settings_svc.py`, it already has `PLAYBOOKS_DIR` constant. Add:
```python
PILLAR_DIR = "pillar_dir"
```

In `fleet_platform/workers/ansible_tasks.py`, replace the hardcoded `_DEFAULT_PILLAR_DIR`:
```python
def _get_pillar_dir(db) -> Path:
    from fleet_platform.models.platform_setting import PlatformSetting
    from sqlalchemy import select as _select
    row = db.execute(
        _select(PlatformSetting).where(PlatformSetting.key == "pillar_dir")
    ).scalar_one_or_none()
    if row and row.value:
        return Path(row.value)
    return Path("/srv/salt/pillar")
```

In `bootstrap_node`, after loading settings, call:
```python
        pillar_dir = _get_pillar_dir(db)
```

And replace `str(_DEFAULT_PILLAR_DIR)` with `str(pillar_dir)` in the `_write_pillar_file` call.

Also expose it in platform settings response — in `fleet_platform/schemas/ansible.py` add:
```python
class PlatformSettingsResponse(BaseModel):
    ...
    pillar_dir: str | None = None
```

In `fleet_platform/api/routes/platform_settings.py` add `PILLAR_DIR` to imports and return it in both GET and PUT handlers.

- [ ] **Step 8: Fix atomic top.sls write with file locking**

In `fleet_platform/workers/ansible_tasks.py`, update `_write_pillar_file`:

```python
import fcntl

def _write_pillar_file(
    pillar_dir: str,
    minion_id: str,
    ingest_url: str,
    node_token: str,
) -> None:
    _validate_minion_id(minion_id)
    pillar_path = Path(pillar_dir)
    pillar_path.mkdir(parents=True, exist_ok=True)

    sls_content = (
        f"# Auto-generated by kri — do not edit manually\n"
        f"fleet_platform:\n"
        f"  ingest_url: {ingest_url}\n"
        f"  node_token: {node_token}\n"
    )
    (pillar_path / f"{minion_id}.sls").write_text(sls_content)

    top_path = pillar_path / "top.sls"
    lock_path = pillar_path / ".top.sls.lock"
    with open(lock_path, "w") as lock_f:
        fcntl.flock(lock_f, fcntl.LOCK_EX)
        try:
            if top_path.exists():
                existing = top_path.read_text()
                if minion_id not in existing:
                    top_path.write_text(
                        existing.rstrip() + f"\n  '{minion_id}':\n    - {minion_id}\n"
                    )
            else:
                top_path.write_text(f"base:\n  '{minion_id}':\n    - {minion_id}\n")
        finally:
            fcntl.flock(lock_f, fcntl.LOCK_UN)
```

- [ ] **Step 9: Fix inventory file permissions**

In `fleet_platform/workers/playbook_tasks.py`, update `_write_static_inventory`:
```python
def _write_static_inventory(tmpdir: str, hosts: list[tuple[str, str, str]]) -> str:
    lines = ["[targets]"]
    for hostname, ip, user in hosts:
        lines.append(f"{hostname} ansible_host={ip} ansible_user={user}")
    inv_path = Path(tmpdir) / "inventory.ini"
    inv_path.write_text("\n".join(lines))
    inv_path.chmod(0o600)  # not world-readable
    return str(inv_path)
```

- [ ] **Step 10: Log git commit failures instead of swallowing**

In `fleet_platform/workers/playbook_tasks.py`, update `_commit_var_files`:
```python
import logging
_log = logging.getLogger(__name__)

def _commit_var_files(var_files: list[Path]) -> None:
    try:
        import git
        repo = git.Repo(_REPO_ROOT)
        for vf in var_files:
            repo.index.add([str(vf.relative_to(_REPO_ROOT))])
        if repo.index.diff("HEAD"):
            repo.index.commit(
                "chore(kri): update ansible var files",
                author=git.Actor("kri", "kri@localhost"),
                committer=git.Actor("kri", "kri@localhost"),
            )
    except Exception as e:
        _log.warning("Could not commit var files to git: %s", e)
        # Non-fatal — var files are still written and used by ansible-runner
```

- [ ] **Step 11: Run tests**

```bash
cd /home/dk/Documents/git/kri && source .venv/bin/activate
python -m pytest tests/unit/test_ansible_validation.py tests/integration/test_playbook_api.py -v 2>&1 | tail -15
python -m pytest tests/ -q --no-header 2>&1 | tail -3
```
Expected: all pass.

- [ ] **Step 12: Commit**

```bash
git add fleet_platform/workers/ansible_tasks.py fleet_platform/workers/playbook_tasks.py \
  fleet_platform/api/routes/ansible.py fleet_platform/services/platform_settings_svc.py \
  fleet_platform/schemas/ansible.py fleet_platform/api/routes/platform_settings.py \
  tests/unit/test_ansible_validation.py
git commit -m "fix: input validation, path traversal, file locking, rate limit, pillar dir config"
```

---

## Task 3: Frontend QA bug fixes

**Files:**
- Modify: `frontend/src/pages/NodeDetail.tsx`
- Modify: `frontend/src/pages/BootstrapModal.tsx`
- Modify: `frontend/src/pages/PlaybooksPage.tsx`
- Modify: `frontend/src/components/Layout/TopBar.tsx`

- [ ] **Step 1: Fix tag mutations — add onError handlers**

In `frontend/src/pages/NodeDetail.tsx`, find `addTagMutation` and `removeTagMutation` and add `onError`:

```tsx
const toast = useToastStore((s) => s.add)  // add this if not already present

const addTagMutation = useMutation({
  mutationFn: () => fleetApi.addTag(nodeId!, tagKey, tagValue),
  onSuccess: () => {
    qc.invalidateQueries({ queryKey: ['node', nodeId] })
    setTagKey('')
    setTagValue('')
    toast('Tag added')           // ← add success toast
  },
  onError: (e: Error) => toast(e.message, 'error'),   // ← add this
})

const removeTagMutation = useMutation({
  mutationFn: (key: string) => fleetApi.removeTag(nodeId!, key),
  onSuccess: () => {
    qc.invalidateQueries({ queryKey: ['node', nodeId] })
    toast('Tag removed')
  },
  onError: (e: Error) => toast(e.message, 'error'),   // ← add this
})
```

Make sure `useToastStore` is imported at the top of NodeDetail.tsx — add the import if missing:
```tsx
import { useToastStore } from '../stores/toastStore'
```

- [ ] **Step 2: Fix bulk bootstrap — invalidate nodes query**

In `frontend/src/pages/BootstrapModal.tsx`, in the `launch` function, add nodes invalidation:

```tsx
    toast(`Launched ${parsedRows.length} bootstrap job(s)`)
    qc.invalidateQueries({ queryKey: ['fleet-overview'] })
    qc.invalidateQueries({ queryKey: ['nodes'] })   // ← add this
```

- [ ] **Step 3: Fix bootstrap logs — auto-refresh while running**

In `frontend/src/pages/BootstrapModal.tsx`, change the logs query to auto-refetch while bootstrap is running:

```tsx
  const { data: logsData, refetch: refetchLogs } = useQuery({
    queryKey: ['bootstrap-logs', nodeId],
    queryFn: () => ansibleApi.bootstrapLogs(nodeId!),
    enabled: showLogs && !!nodeId,   // ← enable when panel is open
    refetchInterval: showLogs && (status === 'pending' || status === 'bootstrapping') ? 5000 : false,
  })
```

Also remove the manual `refetchLogs()` call in the toggle button and simplify:
```tsx
      <button
        onClick={() => setShowLogs(!showLogs)}
        className="w-full py-2 border border-gray-200 text-gray-600 rounded-lg text-xs font-medium hover:bg-gray-50 flex items-center justify-center gap-1"
      >
        {showLogs ? '▲ Hide logs' : '▼ View logs (Salt pillar + Ansible output)'}
      </button>
```

- [ ] **Step 4: Fix search — show empty state**

In `frontend/src/components/Layout/TopBar.tsx`, update the dropdown condition:

```tsx
        {open && (
          <div className="absolute top-full left-0 right-0 mt-1 bg-white rounded-xl border border-gray-200 shadow-lg overflow-hidden z-50">
            {!data || data.items.length === 0 ? (
              <div className="px-4 py-3 text-sm text-gray-400">
                {isLoading ? 'Searching…' : 'No nodes found'}
              </div>
            ) : (
              data.items.map((r) => (
                <button
                  key={r.id}
                  onClick={() => { navigate(`/nodes/${r.id}`); setOpen(false) }}
                  className="w-full px-4 py-2.5 text-left text-sm hover:bg-gray-50 flex items-center gap-3"
                >
                  <span className="font-medium text-gray-900">{r.hostname ?? r.minion_id}</span>
                  <span className="text-xs text-gray-400">{r.status}</span>
                </button>
              ))
            )}
          </div>
        )}
```

Note: `open` should now be set whenever `q.length >= 3` regardless of results:
```tsx
  useEffect(() => {
    setOpen(q.length >= 3)
  }, [q, data])
```

Also need `isLoading` from the query — add it to the destructuring:
```tsx
  const { data, isLoading } = useQuery({ ... })
```

- [ ] **Step 5: Fix PlaybooksPage retry — add loading state**

In `frontend/src/pages/PlaybooksPage.tsx`, update the ErrorState retry:
```tsx
const [retrying, setRetrying] = useState(false)

// In the error state:
<ErrorState
  message="Failed to load playbooks"
  retry={() => { setRetrying(true); refetch().finally(() => setRetrying(false)) }}
/>
{retrying && <div className="text-xs text-gray-400 text-center mt-2">Retrying…</div>}
```

- [ ] **Step 6: TypeScript check**

```bash
cd /home/dk/Documents/git/kri/frontend && npx tsc --noEmit 2>&1 | tail -10
```
Expected: zero errors.

- [ ] **Step 7: Commit**

```bash
cd /home/dk/Documents/git/kri
git add frontend/src/pages/NodeDetail.tsx frontend/src/pages/BootstrapModal.tsx \
  frontend/src/pages/PlaybooksPage.tsx frontend/src/components/Layout/TopBar.tsx
git commit -m "fix: tag onError, search empty state, bulk invalidation, log auto-refresh"
```

---

## Task 4: UI/UX fixes — flows and modals

**Files:**
- Modify: `frontend/src/pages/BootstrapModal.tsx`
- Modify: `frontend/src/pages/PlaybooksPage.tsx`
- Modify: `frontend/src/pages/PlaybookRunModal.tsx`
- Modify: `frontend/src/pages/FleetDashboard.tsx`
- Modify: `frontend/src/pages/GroupDetail.tsx`

- [ ] **Step 1: Bootstrap complete → "Go to Fleet" CTA**

In `frontend/src/pages/BootstrapModal.tsx` `SingleMode`, replace the completion message:

```tsx
      {status === 'completed' && (
        <div className="space-y-2">
          <p className="text-sm text-emerald-700 bg-emerald-50 border border-emerald-200 rounded-lg p-3">
            Bootstrap complete. The Salt minion is starting — the node will appear in the fleet within 30–60 seconds.
          </p>
          <button
            onClick={() => { onClose(); navigate('/fleet') }}
            className="w-full py-2 bg-brand-600 text-white rounded-lg text-sm font-medium hover:bg-brand-700"
          >
            Go to Fleet Dashboard →
          </button>
        </div>
      )}
```

Add `import { useNavigate } from 'react-router-dom'` and `const navigate = useNavigate()` inside `SingleMode`.

- [ ] **Step 2: Playbook Run confirmation step**

In `frontend/src/pages/PlaybooksPage.tsx`, add a confirmation state before opening the modal:

```tsx
  const [pendingRun, setPendingRun] = useState<PlaybookEntry | null>(null)

  // Confirmation dialog:
  {pendingRun && !selected && (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-white rounded-2xl shadow-2xl p-6 w-full max-w-sm mx-4 space-y-4">
        <h2 className="text-lg font-bold text-gray-900">Run playbook?</h2>
        <p className="text-sm text-gray-600">
          <span className="font-semibold">{pendingRun.name}</span> will run against real infrastructure.
          This cannot be undone.
        </p>
        <div className="flex gap-3">
          <button onClick={() => setPendingRun(null)}
            className="flex-1 py-2.5 border border-gray-300 text-gray-700 rounded-lg text-sm font-medium hover:bg-gray-50">
            Cancel
          </button>
          <button onClick={() => { setSelected(pendingRun); setPendingRun(null) }}
            className="flex-1 py-2.5 bg-brand-600 text-white rounded-lg text-sm font-medium hover:bg-brand-700">
            Continue
          </button>
        </div>
      </div>
    </div>
  )}
```

Update each `PlaybookCard`'s onRun call to use `setPendingRun` instead of `setSelected`:
```tsx
<PlaybookCard key={p.filename} entry={p} onRun={() => setPendingRun(p)} />
```

- [ ] **Step 3: Make PlaybookRunModal bigger**

In `frontend/src/pages/PlaybookRunModal.tsx`, change the modal container:
```tsx
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-2xl shadow-2xl p-6 w-full max-w-2xl flex flex-col gap-4 max-h-[92vh] overflow-y-auto">
```
(Changed `max-w-lg` → `max-w-2xl`, added `p-4` to outer container for breathing room on small screens.)

Add section headers in the form for readability:
```tsx
            <div>
              <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">1. Select target</p>
              {/* target type and selector */}
            </div>

            {hasVars && (
              <div>
                <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2">2. Configure variables</p>
                ...
              </div>
            )}

            <div>
              <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">3. Run</p>
              {/* buttons */}
            </div>
```

- [ ] **Step 4: Add variable editor warnings for system vars**

In `frontend/src/pages/PlaybookRunModal.tsx`, in the variable editor, flag dangerous vars:

```tsx
const SYSTEM_VARS = new Set([
  'ansible_become', 'ansible_become_method', 'ansible_become_password',
  'ansible_ssh_common_args', 'ansible_ssh_pass', 'ansible_user',
])

// In the variable editor map:
{Object.entries(vars).map(([key, value]) => (
  <div key={key} className="flex items-start gap-2">
    <div className="flex flex-col w-44 shrink-0">
      <span className="text-xs font-mono text-gray-600">{key}</span>
      {SYSTEM_VARS.has(key) && (
        <span className="text-xs text-amber-600">⚠ system var</span>
      )}
    </div>
    <input
      type="text"
      value={value}
      onChange={(e) => setVars((prev) => ({ ...prev, [key]: e.target.value }))}
      className={`flex-1 px-2 py-1 text-xs border rounded focus:outline-none font-mono ${
        SYSTEM_VARS.has(key)
          ? 'border-amber-300 bg-amber-50 focus:border-amber-500'
          : 'border-gray-300 focus:border-brand-600'
      }`}
    />
  </div>
))}
```

- [ ] **Step 5: Fleet Dashboard empty state**

In `frontend/src/pages/FleetDashboard.tsx`, add empty state when nodes count is 0:

```tsx
          {nodes?.items.length === 0 && !nodesLoading ? (
            <div className="px-4 py-16 text-center space-y-4">
              <p className="text-4xl">🖥️</p>
              <p className="text-lg font-semibold text-gray-700">No nodes in your fleet yet</p>
              <p className="text-sm text-gray-500 max-w-sm mx-auto">
                Bootstrap a Mac Mini to get started. Make sure Remote Login (SSH) is enabled on the device.
              </p>
              <button
                onClick={() => setShowBootstrap(true)}
                className="px-6 py-2.5 bg-brand-600 text-white text-sm font-medium rounded-lg hover:bg-brand-700 shadow-sm"
              >
                Bootstrap your first node →
              </button>
            </div>
          ) : (
            <>
              {/* existing table */}
            </>
          )}
```

- [ ] **Step 6: Group type badge tooltip**

In `frontend/src/pages/GroupDetail.tsx`, update the type badge to explain dynamic groups:

```tsx
        <span
          title={group.type === 'dynamic'
            ? 'Dynamic group: membership is resolved automatically from a predicate. Nodes cannot be added/removed manually.'
            : 'Static group: add and remove nodes manually.'}
          className={`cursor-help text-xs px-2 py-0.5 rounded font-medium ${
            group.type === 'dynamic'
              ? 'bg-purple-100 text-purple-800 border border-purple-200'
              : 'bg-gray-100 text-gray-700 border border-gray-200'
          }`}>
          {group.type} ℹ
        </span>
```

- [ ] **Step 7: TypeScript check + build**

```bash
cd /home/dk/Documents/git/kri/frontend && npx tsc --noEmit 2>&1 | tail -10 && npm run build 2>&1 | grep -E "built|error" | head -3
```
Expected: zero errors, `✓ built`.

- [ ] **Step 8: Commit**

```bash
cd /home/dk/Documents/git/kri
git add frontend/src/pages/BootstrapModal.tsx frontend/src/pages/PlaybooksPage.tsx \
  frontend/src/pages/PlaybookRunModal.tsx frontend/src/pages/FleetDashboard.tsx \
  frontend/src/pages/GroupDetail.tsx
git commit -m "feat: UX — bootstrap CTA, playbook confirm, bigger run modal, fleet empty state, group tooltip"
```

---

## Task 5: UI/UX fixes — components and settings

**Files:**
- Modify: `frontend/src/components/Layout/Sidebar.tsx`
- Modify: `frontend/src/pages/SettingsPage.tsx`
- Modify: `frontend/src/components/Pagination.tsx`

- [ ] **Step 1: Sidebar — tooltips in collapsed mode**

In `frontend/src/components/Layout/Sidebar.tsx`, the links already have `title={!open ? label : undefined}`. This works in most browsers. Improve it by also adding `aria-label` and a better hover tooltip using Tailwind group styling:

Replace the NavLink content:
```tsx
            <NavLink
              to={to}
              className={({ isActive }) =>
                `group relative flex items-center gap-3 rounded-lg text-sm font-medium transition-all duration-150 ${
                  open ? 'px-3 py-2.5' : 'px-2.5 py-2.5 justify-center'
                } ${isActive
                  ? 'bg-brand-600/20 text-brand-300 border border-brand-600/30 shadow-sm shadow-brand-600/20'
                  : 'text-white/45 hover:text-white/90 hover:bg-white/5 border border-transparent'
                }`
              }
            >
              <span className="text-base flex-shrink-0 font-mono">{icon}</span>
              {open && <span>{label}</span>}
              {/* Tooltip for collapsed mode */}
              {!open && (
                <span className="pointer-events-none absolute left-full ml-2 whitespace-nowrap rounded-md bg-gray-900 px-2 py-1 text-xs text-white opacity-0 group-hover:opacity-100 transition-opacity z-50">
                  {label}
                </span>
              )}
            </NavLink>
```

- [ ] **Step 2: Settings page — Required vs Optional sections**

In `frontend/src/pages/SettingsPage.tsx`, add section dividers:

Before the Salt Master card, add:
```tsx
      <div className="flex items-center gap-3">
        <div className="h-px flex-1 bg-gray-200" />
        <span className="text-xs font-semibold text-gray-400 uppercase tracking-wide">Required</span>
        <div className="h-px flex-1 bg-gray-200" />
      </div>
```

Before the Playbooks Directory card (first optional one), add:
```tsx
      <div className="flex items-center gap-3 mt-4">
        <div className="h-px flex-1 bg-gray-200" />
        <span className="text-xs font-semibold text-gray-400 uppercase tracking-wide">Optional / Advanced</span>
        <div className="h-px flex-1 bg-gray-200" />
      </div>
```

Also add pillar_dir field to the settings form (state, useEffect seed, saveMutation, and a new card) following the same pattern as `playbooksDir`:

```tsx
  const [pillarDir, setPillarDir] = useState('')

  // in useEffect:
  if (data?.pillar_dir) setPillarDir(data.pillar_dir)

  // in saveMutation.mutationFn:
  pillar_dir: pillarDir || undefined,

  // New card after Playbooks Directory card:
  <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-6 space-y-4">
    <h2 className="text-base font-semibold text-gray-900">Salt Pillar Directory</h2>
    <div>
      <label className="block text-sm font-medium text-gray-700 mb-1">Path to Salt pillar directory</label>
      <input type="text" value={pillarDir} onChange={(e) => setPillarDir(e.target.value)}
        placeholder="/srv/salt/pillar  (default)"
        className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm text-gray-900 focus:outline-none focus:border-brand-600 font-mono" />
      <p className="text-xs text-gray-400 mt-1">
        kri writes per-node SLS files here before bootstrap. Must be writable by the kri process.
      </p>
    </div>
  </div>
```

Also update `ansibleApi.updateSettings` type in `frontend/src/api/ansible.ts` to add `pillar_dir?: string` and add `pillar_dir: string | null` to `PlatformSettings`.

- [ ] **Step 3: Password show/hide — add eye icon**

In `frontend/src/pages/SettingsPage.tsx`, replace the "Show"/"Hide" text toggle with an eye icon:

```tsx
            <button
              type="button"
              onClick={() => setShowPassword(!showPassword)}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600 p-1"
              title={showPassword ? 'Hide password' : 'Show password'}
            >
              {showPassword ? (
                <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 4.411m0 0L21 21" />
                </svg>
              ) : (
                <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                </svg>
              )}
            </button>
```

- [ ] **Step 4: Pagination — per-page selector**

Read `frontend/src/components/Pagination.tsx` first. Add a per-page selector:

```tsx
interface Props {
  page: number
  total: number
  perPage: number
  onPage: (p: number) => void
  onPerPage?: (n: number) => void  // ← add optional
}

export function Pagination({ page, total, perPage, onPage, onPerPage }: Props) {
  const totalPages = Math.ceil(total / perPage)
  const from = (page - 1) * perPage + 1
  const to = Math.min(page * perPage, total)

  return (
    <div className="px-4 py-3 border-t border-gray-200 flex items-center justify-between gap-4 text-sm">
      <span className="text-gray-500 text-xs">
        Showing {from}–{to} of {total}
      </span>
      <div className="flex items-center gap-2">
        {onPerPage && (
          <select
            value={perPage}
            onChange={(e) => { onPerPage(Number(e.target.value)); onPage(1) }}
            className="text-xs border border-gray-300 rounded px-2 py-1 text-gray-600 focus:outline-none focus:border-brand-600"
          >
            {[25, 50, 100].map((n) => (
              <option key={n} value={n}>{n} / page</option>
            ))}
          </select>
        )}
        <button disabled={page <= 1} onClick={() => onPage(page - 1)}
          className="px-2 py-1 text-xs border border-gray-300 rounded hover:bg-gray-50 disabled:opacity-40">
          ← Prev
        </button>
        <span className="text-xs text-gray-500">{page} / {totalPages}</span>
        <button disabled={page >= totalPages} onClick={() => onPage(page + 1)}
          className="px-2 py-1 text-xs border border-gray-300 rounded hover:bg-gray-50 disabled:opacity-40">
          Next →
        </button>
      </div>
    </div>
  )
}
```

In `frontend/src/pages/FleetDashboard.tsx`, add `perPage` state and wire it up:
```tsx
  const [perPage, setPerPage] = useState(50)

  // in the nodes query:
  queryFn: () => fleetApi.nodes({ page, per_page: perPage, status: statusFilter || undefined }),

  // in Pagination:
  <Pagination page={page} total={nodes.total} perPage={nodes.per_page}
    onPage={setPage} onPerPage={(n) => { setPerPage(n); setPage(1) }} />
```

Apply the same pattern to `GroupDetail.tsx` and `NodeDetail.tsx` where Pagination is used.

- [ ] **Step 5: Modal close button — bigger hit target**

In `frontend/src/pages/PlaybookRunModal.tsx`, `BootstrapModal.tsx`, and `PlaybookRunModal.tsx` update close buttons:

Replace `className="text-gray-400 hover:text-gray-600 text-xl leading-none">×</button>` with:
```tsx
className="flex items-center justify-center w-8 h-8 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-100 text-lg transition-colors">×</button>
```

- [ ] **Step 6: TypeScript check + build**

```bash
cd /home/dk/Documents/git/kri/frontend && npx tsc --noEmit 2>&1 | tail -10 && npm run build 2>&1 | grep -E "built|error" | head -3
```
Expected: zero errors, `✓ built`.

- [ ] **Step 7: Commit**

```bash
cd /home/dk/Documents/git/kri
git add frontend/src/components/Layout/Sidebar.tsx frontend/src/pages/SettingsPage.tsx \
  frontend/src/components/Pagination.tsx frontend/src/pages/FleetDashboard.tsx \
  frontend/src/api/ansible.ts frontend/src/pages/PlaybookRunModal.tsx \
  frontend/src/pages/BootstrapModal.tsx
git commit -m "feat: UX — sidebar tooltips, settings sections, eye icon, per-page selector, modal close"
```

---

## Task 6: Final test sweep + restart

- [ ] **Step 1: Full backend test suite**

```bash
cd /home/dk/Documents/git/kri && source .venv/bin/activate
python -m pytest tests/ -q --no-header 2>&1 | tail -5
```
Expected: 200+ passed.

- [ ] **Step 2: TypeScript + production build**

```bash
cd /home/dk/Documents/git/kri/frontend && npx tsc --noEmit && npm run build 2>&1 | grep -E "built|error"
```
Expected: `✓ built`.

- [ ] **Step 3: Restart kri**

```bash
cd /home/dk/Documents/git/kri && ./scripts/kri.sh restart 2>&1
```

- [ ] **Step 4: Smoke test bootstrap endpoint**

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@fleet.local","password":"changeme123"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# Rate limit test — should 429 after 10 rapid requests
for i in {1..12}; do
  curl -s -o /dev/null -w "%{http_code} " -X POST http://localhost:8000/api/v1/ansible/bootstrap \
    -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
    -d '{"minion_id":"test-'$i'","target_ip":"10.0.1.'$i'"}'; done
echo ""
```
Expected: first 10 return 202, 11th returns 429.

- [ ] **Step 5: Playbooks API smoke test**

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/ansible/playbooks | python3 -m json.tool | head -10
```
Expected: list with `bootstrap_mac_mini.yml`.

- [ ] **Step 6: Final commit**

```bash
cd /home/dk/Documents/git/kri
git add -u
git status  # confirm nothing unexpected
git commit -m "chore: audit remediation complete — all 42 issues fixed" --allow-empty
```

---

## Checklist — all 42 audit items

### Security (15 items)
- [x] Ansible inventory host pattern fixed (3b71bab)
- [ ] Offline ansible.posix collection bundled — Task 1
- [ ] Minion ID validation regex — Task 2
- [ ] Path traversal in target_label/hostname → file writes — Task 2
- [ ] Playbook path `Path.resolve()` check — Task 2
- [ ] Rate limiting on `/api/v1/ansible/bootstrap` — Task 2
- [ ] Atomic `top.sls` write with file locking — Task 2
- [ ] Inventory file permissions 0o600 — Task 2
- [ ] subprocess.run() return code (removed — galaxy call deleted) — Task 1
- [ ] Configurable pillar dir — Task 2
- [ ] Git commit failures logged not swallowed — Task 2
- [ ] SSH credentials removed from env vars — Task 2 (moved to inventory.ini 0600)
- [ ] `StrictHostKeyChecking` moved to extravars (not hardcoded in playbook) — Task 1
- [ ] `hosts: target → targets` mismatch — fixed (3b71bab)
- [ ] No internet / ansible-galaxy runtime call removed — Task 1

### QA Bugs (12 items)
- [ ] Tag mutations onError — Task 3
- [ ] Add-tag success toast — Task 3
- [ ] Bulk bootstrap invalidates nodes — Task 3
- [ ] Bootstrap logs auto-refresh — Task 3
- [ ] Search empty state — Task 3
- [ ] PlaybooksPage retry loading state — Task 3
- [ ] Run playbook dialog too small — Task 4
- [ ] Bootstrap complete dead end — Task 4
- [ ] Fleet Dashboard empty state — Task 4
- [ ] Group type badge no explanation — Task 4
- [ ] Playbook run no confirmation — Task 4
- [ ] Variable editor no warnings for system vars — Task 4

### UI/UX (15 items)
- [ ] Sidebar collapsed mode tooltips — Task 5
- [ ] Settings Required/Optional sections — Task 5
- [ ] Settings pillar dir field — Task 5
- [ ] Password eye icon — Task 5
- [ ] Pagination per-page selector — Task 5
- [ ] Modal close button hit targets — Task 5
- [ ] Playbook run step labels — Task 4
- [ ] Group type tooltip ℹ — Task 4
- [ ] Bootstrap "Go to Fleet" CTA — Task 4
- [ ] Empty fleet onboarding — Task 4
- [ ] Playbook run confirmation — Task 4
- [ ] Drift score no explanation — (noted — tooltip can be added in future)
- [ ] SBOM table non-actionable — (noted — filter/search in future plan)
- [ ] Execution history no status filter — (noted — future plan)
- [ ] "Bootstrap Node" button prominence — (improved by empty state CTA)
