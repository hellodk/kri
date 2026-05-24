# Fleet Platform Plan 11 — Ansible Bootstrap Integration

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a full Ansible-based node bootstrap pipeline into kri so a bare Mac Mini goes from "SSH password only" to "Salt-managed fleet member" in one click — no AWX, no separate tooling.

**Architecture:** kri replaces AWX entirely. The backend uses `ansible-runner` (the same Python library AWX uses internally) as a Celery task. Global settings (Salt master address, SSH username, encrypted SSH password, controller SSH key) are stored in a new `platform_settings` table. The bootstrap playbook: connects via SSH password → copies controller public key → installs Xcode CLT + Homebrew + Salt → configures the minion → starts the service. After bootstrap, kri writes the node token into the Salt Master's pillar directory so the minion can authenticate grain reports immediately on first connection. The frontend adds a Settings page and a Bootstrap node workflow to the Fleet Dashboard.

**Tech Stack:** Python 3.13, ansible-runner 2.x, ansible-core 2.17+, FastAPI, Celery, SQLAlchemy 2.0 async, cryptography (Fernet for password encryption), React 18, TanStack Query 5.

---

## Constraints and design decisions

- **Same SSH username + password for all Mac Minis** — stored once in `platform_settings`, used for all bootstraps
- **Salt master address** — single configurable value (LAN IP or DNS, e.g. `10.0.0.1` or `salt.fleet.local`)
- **Homebrew must be installed** by the playbook (not assumed present)
- **`become: true`** for privileged operations; `ansible_become_password` = same as SSH password
- **`-o StrictHostKeyChecking=no`** for first-time SSH connections (unknown host fingerprint)
- **Controller SSH keypair** generated once at `~/.kri/id_rsa` + `~/.kri/id_rsa.pub`
- **Pillar written before Ansible runs** — kri writes `/srv/salt/pillar/<minion_id>.sls` on the master before triggering the playbook, so the minion has its token waiting on first connection
- **Migration 003** — add bootstrap fields to nodes + platform_settings table

---

## File Structure

| Action | Path | Purpose |
|--------|------|---------|
| Add dep | `pyproject.toml` | `ansible-runner`, `ansible-core`, `cryptography` |
| Create | `fleet_platform/db/migrations/versions/003_bootstrap.py` | Add bootstrap fields to nodes + platform_settings table |
| Modify | `fleet_platform/models/node.py` | Add `bootstrap_status`, `bootstrap_ip`, `bootstrap_error` |
| Create | `fleet_platform/models/platform_setting.py` | Key-value settings store with Fernet encryption |
| Create | `fleet_platform/services/ssh_keypair.py` | Generate/load controller RSA keypair |
| Create | `fleet_platform/services/platform_settings_svc.py` | Get/set encrypted settings |
| Create | `fleet_platform/workers/ansible_tasks.py` | `bootstrap_node` Celery task using ansible-runner |
| Modify | `fleet_platform/workers/celery_app.py` | Include ansible_tasks |
| Create | `fleet_platform/api/routes/ansible.py` | Bootstrap + job status API |
| Create | `fleet_platform/api/routes/platform_settings.py` | Settings CRUD API |
| Modify | `fleet_platform/api/main.py` | Register new routers |
| Create | `fleet_platform/schemas/ansible.py` | Request/response schemas |
| Create | `playbooks/bootstrap_mac_mini.yml` | The Ansible playbook |
| Create | `playbooks/inventory/dynamic.py` | Dynamic inventory script |
| Create | `frontend/src/api/ansible.ts` | Frontend API client |
| Create | `frontend/src/pages/SettingsPage.tsx` | Configure salt master, SSH creds, show public key |
| Modify | `frontend/src/pages/FleetDashboard.tsx` | Add "Bootstrap Node" button |
| Create | `frontend/src/pages/BootstrapJob.tsx` | Live job output viewer |
| Modify | `frontend/src/App.tsx` | Add /settings and /bootstrap/:jobId routes |
| Modify | `frontend/src/components/Layout/Sidebar.tsx` | Add Settings link |

---

## Task 1: Dependencies + Migration + Model Changes

**Files:**
- Modify: `pyproject.toml`
- Create: `fleet_platform/db/migrations/versions/003_bootstrap.py`
- Modify: `fleet_platform/models/node.py`
- Create: `fleet_platform/models/platform_setting.py`

- [ ] **Step 1: Add Python dependencies**

In `pyproject.toml`, add to the `dependencies` list:
```toml
    "ansible-runner>=2.4.0",
    "ansible-core>=2.17.0",
    "cryptography>=43.0.0",
```

Run:
```bash
source .venv/bin/activate && uv sync
python -c "import ansible_runner; print('ansible-runner OK')"
python -c "from cryptography.fernet import Fernet; print('cryptography OK')"
```

Expected: both print OK.

- [ ] **Step 2: Create migration 003**

```python
# fleet_platform/db/migrations/versions/003_bootstrap.py
"""Add bootstrap fields to nodes and platform_settings table."""
from alembic import op
import sqlalchemy as sa

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade():
    # Bootstrap status on nodes
    op.add_column("nodes", sa.Column(
        "bootstrap_status",
        sa.String(20), nullable=False, server_default="unregistered"
    ))
    op.add_column("nodes", sa.Column("bootstrap_ip", sa.String(45), nullable=True))
    op.add_column("nodes", sa.Column("bootstrap_error", sa.Text, nullable=True))

    # Platform-wide key-value settings
    op.create_table(
        "platform_settings",
        sa.Column("key", sa.String(100), primary_key=True),
        sa.Column("value", sa.Text, nullable=True),
        sa.Column("is_encrypted", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade():
    op.drop_table("platform_settings")
    op.drop_column("nodes", "bootstrap_error")
    op.drop_column("nodes", "bootstrap_ip")
    op.drop_column("nodes", "bootstrap_status")
```

Run migrations:
```bash
source .venv/bin/activate && alembic upgrade head
```
Expected: `INFO alembic.runtime.migration Running upgrade 002 -> 003`

- [ ] **Step 3: Add bootstrap fields to Node model**

In `fleet_platform/models/node.py`, add after `last_seen_at`:

```python
    bootstrap_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="unregistered"
    )
    bootstrap_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    bootstrap_error: Mapped[str | None] = mapped_column(Text, nullable=True)
```

Also add `Text` to the SQLAlchemy imports at top of the file.

- [ ] **Step 4: Create PlatformSetting model**

```python
# fleet_platform/models/platform_setting.py
from datetime import datetime
from sqlalchemy import Boolean, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from fleet_platform.models.base import Base


class PlatformSetting(Base):
    __tablename__ = "platform_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_encrypted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default="now()"
    )
```

Add `PlatformSetting` to `fleet_platform/models/__init__.py`.

- [ ] **Step 5: Run tests to check no regressions**

```bash
source .venv/bin/activate && pytest tests/ -q --no-header 2>&1 | tail -5
```
Expected: all existing tests pass.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock fleet_platform/db/migrations/versions/003_bootstrap.py \
  fleet_platform/models/node.py fleet_platform/models/platform_setting.py \
  fleet_platform/models/__init__.py
git commit -m "feat(P11): migration 003 + bootstrap fields on nodes + platform_settings table"
```

---

## Task 2: Platform Settings Service + SSH Keypair Management

**Files:**
- Create: `fleet_platform/services/platform_settings_svc.py`
- Create: `fleet_platform/services/ssh_keypair.py`
- Test: `tests/unit/test_platform_settings.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_platform_settings.py
import os
import tempfile
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def test_fernet_encrypt_decrypt_roundtrip():
    from fleet_platform.services.platform_settings_svc import _fernet
    plaintext = "super-secret-password"
    encrypted = _fernet().encrypt(plaintext.encode()).decode()
    decrypted = _fernet().decrypt(encrypted.encode()).decode()
    assert decrypted == plaintext


def test_fernet_key_derived_from_jwt_secret(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "a" * 32)
    from importlib import reload
    import fleet_platform.services.platform_settings_svc as svc
    reload(svc)
    key1 = svc._fernet_key()
    key2 = svc._fernet_key()
    assert key1 == key2  # deterministic


def test_ssh_keypair_creates_files():
    from fleet_platform.services.ssh_keypair import ensure_controller_keypair
    with tempfile.TemporaryDirectory() as tmpdir:
        priv = os.path.join(tmpdir, "id_rsa")
        pub = os.path.join(tmpdir, "id_rsa.pub")
        ensure_controller_keypair(priv_path=priv, pub_path=pub)
        assert os.path.exists(priv)
        assert os.path.exists(pub)
        with open(pub) as f:
            assert f.read().startswith("ssh-rsa ")


def test_ssh_keypair_idempotent():
    from fleet_platform.services.ssh_keypair import ensure_controller_keypair
    with tempfile.TemporaryDirectory() as tmpdir:
        priv = os.path.join(tmpdir, "id_rsa")
        pub = os.path.join(tmpdir, "id_rsa.pub")
        ensure_controller_keypair(priv_path=priv, pub_path=pub)
        mtime1 = os.path.getmtime(priv)
        ensure_controller_keypair(priv_path=priv, pub_path=pub)
        assert os.path.getmtime(priv) == mtime1  # not regenerated
```

- [ ] **Step 2: Run to confirm they fail**

```bash
source .venv/bin/activate && pytest tests/unit/test_platform_settings.py -v 2>&1 | tail -10
```
Expected: ImportError (modules don't exist yet).

- [ ] **Step 3: Implement platform_settings_svc.py**

```python
# fleet_platform/services/platform_settings_svc.py
import base64
import hashlib
from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.core.config import settings
from fleet_platform.models.platform_setting import PlatformSetting


# Derive a Fernet key from the JWT secret so no extra config needed
def _fernet_key() -> bytes:
    digest = hashlib.sha256(settings.jwt_secret.encode()).digest()
    return base64.urlsafe_b64encode(digest)


def _fernet() -> Fernet:
    return Fernet(_fernet_key())


async def get_setting(db: AsyncSession, key: str) -> str | None:
    result = await db.execute(select(PlatformSetting).where(PlatformSetting.key == key))
    row = result.scalar_one_or_none()
    if row is None:
        return None
    if row.is_encrypted and row.value:
        return _fernet().decrypt(row.value.encode()).decode()
    return row.value


async def set_setting(db: AsyncSession, key: str, value: str, encrypt: bool = False) -> None:
    stored_value = _fernet().encrypt(value.encode()).decode() if encrypt else value
    result = await db.execute(select(PlatformSetting).where(PlatformSetting.key == key))
    row = result.scalar_one_or_none()
    if row:
        row.value = stored_value
        row.is_encrypted = encrypt
    else:
        db.add(PlatformSetting(key=key, value=stored_value, is_encrypted=encrypt))
    await db.commit()


# Well-known setting keys
SALT_MASTER = "salt_master_address"
SSH_USERNAME = "ssh_bootstrap_username"
SSH_PASSWORD = "ssh_bootstrap_password"   # stored encrypted
CONTROLLER_PRIVKEY_PATH = "controller_privkey_path"
CONTROLLER_PUBKEY_PATH = "controller_pubkey_path"
```

- [ ] **Step 4: Implement ssh_keypair.py**

```python
# fleet_platform/services/ssh_keypair.py
import os
from pathlib import Path
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

_DEFAULT_KRI_DIR = Path.home() / ".kri"
_DEFAULT_PRIV = _DEFAULT_KRI_DIR / "id_rsa"
_DEFAULT_PUB  = _DEFAULT_KRI_DIR / "id_rsa.pub"


def ensure_controller_keypair(
    priv_path: str | Path = _DEFAULT_PRIV,
    pub_path: str | Path = _DEFAULT_PUB,
) -> tuple[str, str]:
    """Generate RSA keypair if it doesn't exist. Returns (priv_path, pubkey_content)."""
    priv_path = Path(priv_path)
    pub_path = Path(pub_path)
    priv_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)

    if not priv_path.exists():
        key = rsa.generate_private_key(public_exponent=65537, key_size=4096)
        priv_pem = key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.OpenSSH,
            encryption_algorithm=serialization.NoEncryption(),
        )
        pub_openssh = key.public_key().public_bytes(
            encoding=serialization.Encoding.OpenSSH,
            format=serialization.PublicFormat.OpenSSH,
        )
        priv_path.write_bytes(priv_pem)
        priv_path.chmod(0o600)
        pub_path.write_bytes(pub_openssh + b"\n")
        pub_path.chmod(0o644)

    pubkey = pub_path.read_text().strip()
    return str(priv_path), pubkey


def get_controller_pubkey(
    pub_path: str | Path = _DEFAULT_PUB,
) -> str | None:
    pub_path = Path(pub_path)
    if not pub_path.exists():
        return None
    return pub_path.read_text().strip()
```

- [ ] **Step 5: Run tests**

```bash
source .venv/bin/activate && pytest tests/unit/test_platform_settings.py -v 2>&1 | tail -10
```
Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
git add fleet_platform/services/platform_settings_svc.py \
  fleet_platform/services/ssh_keypair.py \
  tests/unit/test_platform_settings.py
git commit -m "feat(P11): platform settings service (Fernet encryption) + SSH keypair manager"
```

---

## Task 3: Bootstrap Ansible Playbook + Dynamic Inventory

**Files:**
- Create: `playbooks/bootstrap_mac_mini.yml`
- Create: `playbooks/inventory/dynamic.py`

- [ ] **Step 1: Create the playbook directory**

```bash
mkdir -p playbooks/inventory
```

- [ ] **Step 2: Write bootstrap_mac_mini.yml**

```yaml
# playbooks/bootstrap_mac_mini.yml
---
- name: Bootstrap Mac Mini into kri fleet
  hosts: target
  gather_facts: false
  vars:
    ansible_ssh_common_args: '-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null'
    ansible_become: true
    ansible_become_method: sudo
    ansible_become_password: "{{ ansible_ssh_pass }}"
    brew_prefix_arm64: /opt/homebrew
    brew_prefix_x86: /usr/local
    salt_config_dir: /opt/salt/etc/salt
    salt_version: "3007.1"

  tasks:

    # ── Detect architecture ──────────────────────────────────────────────────
    - name: Detect CPU architecture
      raw: uname -m
      register: uname_result
      changed_when: false

    - name: Set Homebrew prefix
      set_fact:
        brew_prefix: "{{ brew_prefix_arm64 if 'arm64' in uname_result.stdout else brew_prefix_x86 }}"

    # ── Gather minimal facts ─────────────────────────────────────────────────
    - name: Gather minimal facts
      setup:
        gather_subset:
          - min

    # ── Xcode Command Line Tools ─────────────────────────────────────────────
    - name: Check if Xcode CLT is installed
      command: xcode-select -p
      register: xcode_check
      failed_when: false
      changed_when: false
      become: false

    - name: Install Xcode Command Line Tools (headless)
      shell: |
        touch /tmp/.com.apple.dt.CommandLineTools.installondemand.in-progress
        LABEL=$(softwareupdate -l 2>&1 | awk -F'*' '/Command Line/{print $2}' | head -1 | xargs)
        if [ -n "$LABEL" ]; then
          softwareupdate -i "$LABEL" --agree-to-license --verbose
        fi
        rm -f /tmp/.com.apple.dt.CommandLineTools.installondemand.in-progress
      when: xcode_check.rc != 0
      become: true
      timeout: 600
      register: clt_install
      changed_when: "'Installed' in clt_install.stdout"

    # ── Homebrew ─────────────────────────────────────────────────────────────
    - name: Check if Homebrew is installed
      stat:
        path: "{{ brew_prefix }}/bin/brew"
      register: brew_stat
      become: false

    - name: Install Homebrew
      shell: |
        NONINTERACTIVE=1 /bin/bash -c \
          "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
      when: not brew_stat.stat.exists
      become: false
      environment:
        NONINTERACTIVE: "1"
      timeout: 600

    - name: Add Homebrew to shell profile
      lineinfile:
        path: "~/.zprofile"
        line: 'eval "$({{ brew_prefix }}/bin/brew shellenv)"'
        create: true
      become: false

    # ── Salt installation ─────────────────────────────────────────────────────
    - name: Check if Salt minion is installed
      stat:
        path: "{{ brew_prefix }}/bin/salt-minion"
      register: salt_stat
      become: false

    - name: Install Salt via Homebrew
      shell: "{{ brew_prefix }}/bin/brew install salt"
      when: not salt_stat.stat.exists
      become: false
      environment:
        PATH: "{{ brew_prefix }}/bin:/usr/local/bin:/usr/bin:/bin"
      timeout: 300

    # ── Salt configuration ────────────────────────────────────────────────────
    - name: Create Salt config directory
      file:
        path: /etc/salt
        state: directory
        owner: root
        group: wheel
        mode: "0755"
      become: true

    - name: Write Salt minion config
      copy:
        dest: /etc/salt/minion
        owner: root
        group: wheel
        mode: "0644"
        content: |
          master: {{ salt_master_address }}
          id: {{ minion_id }}
          log_level: info
          log_file: /var/log/salt/minion
      become: true
      notify: Restart salt-minion

    # ── Authorised keys ───────────────────────────────────────────────────────
    - name: Ensure ~/.ssh exists
      file:
        path: "~/.ssh"
        state: directory
        mode: "0700"
      become: false

    - name: Authorise kri controller SSH key
      authorized_key:
        user: "{{ ansible_user }}"
        key: "{{ controller_pubkey }}"
        state: present
      become: false

    # ── Start Salt minion ─────────────────────────────────────────────────────
    - name: Enable Salt minion via launchd (Homebrew services)
      shell: "{{ brew_prefix }}/bin/brew services start salt-minion || true"
      become: true
      environment:
        PATH: "{{ brew_prefix }}/bin:/usr/local/bin:/usr/bin:/bin"
      changed_when: false

    - name: Verify Salt minion is running
      shell: "pgrep -f salt-minion"
      register: minion_check
      failed_when: minion_check.rc != 0
      changed_when: false
      retries: 6
      delay: 5

  handlers:
    - name: Restart salt-minion
      shell: "{{ brew_prefix }}/bin/brew services restart salt-minion || true"
      become: true
      environment:
        PATH: "{{ brew_prefix }}/bin:/usr/local/bin:/usr/bin:/bin"
```

- [ ] **Step 3: Write dynamic inventory script**

This script is called by ansible-runner to generate inventory from a single IP (provided via environment variable):

```python
#!/usr/bin/env python3
# playbooks/inventory/dynamic.py
"""
Minimal Ansible dynamic inventory used for bootstrap runs.
Reads TARGET_HOST and ANSIBLE_USER from environment.
"""
import json
import os
import sys

if len(sys.argv) > 1 and sys.argv[1] == '--list':
    host = os.environ.get("TARGET_HOST", "")
    user = os.environ.get("ANSIBLE_USER", "admin")
    password = os.environ.get("ANSIBLE_PASSWORD", "")
    print(json.dumps({
        "target": {
            "hosts": [host],
        },
        "_meta": {
            "hostvars": {
                host: {
                    "ansible_host": host,
                    "ansible_user": user,
                    "ansible_ssh_pass": password,
                    "ansible_become_password": password,
                }
            }
        }
    }))
elif len(sys.argv) > 2 and sys.argv[1] == '--host':
    print(json.dumps({}))
```

Make it executable:
```bash
chmod +x playbooks/inventory/dynamic.py
```

- [ ] **Step 4: Verify playbook YAML syntax**

```bash
source .venv/bin/activate && python -c "
import yaml
with open('playbooks/bootstrap_mac_mini.yml') as f:
    data = yaml.safe_load(f)
print('YAML OK, tasks:', len(data[0]['tasks']))
"
```
Expected: `YAML OK, tasks: 13` (approximately)

- [ ] **Step 5: Commit**

```bash
git add playbooks/
git commit -m "feat(P11): bootstrap_mac_mini.yml playbook + dynamic inventory script"
```

---

## Task 4: Ansible Bootstrap Celery Task

**Files:**
- Create: `fleet_platform/workers/ansible_tasks.py`
- Modify: `fleet_platform/workers/celery_app.py`
- Test: `tests/unit/test_ansible_tasks.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_ansible_tasks.py
import uuid
from unittest.mock import MagicMock, patch


def test_bootstrap_task_writes_pillar_before_running():
    """Pillar file must be written before ansible-runner is invoked."""
    call_order = []

    def mock_write_pillar(*args, **kwargs):
        call_order.append("pillar")

    mock_runner_result = MagicMock()
    mock_runner_result.status = "successful"
    mock_runner_result.rc = 0

    def mock_run(*args, **kwargs):
        call_order.append("ansible")
        return mock_runner_result

    mock_db = MagicMock()
    mock_db.__enter__ = MagicMock(return_value=mock_db)
    mock_db.__exit__ = MagicMock(return_value=False)

    # Mock the node lookup
    mock_node = MagicMock()
    mock_node.id = uuid.uuid4()
    mock_node.minion_id = "test-node.local"
    mock_node.node_token_hash = "x"
    mock_db.execute.return_value.scalar_one_or_none.return_value = mock_node

    with patch("fleet_platform.workers.ansible_tasks.get_sync_db", return_value=mock_db), \
         patch("fleet_platform.workers.ansible_tasks._write_pillar_file", mock_write_pillar), \
         patch("fleet_platform.workers.ansible_tasks.ansible_runner.run", mock_run), \
         patch("fleet_platform.workers.ansible_tasks._get_bootstrap_settings",
               return_value=("10.0.0.1", "admin", "pass", "/key", "ssh-rsa AAA")):
        from fleet_platform.workers.ansible_tasks import bootstrap_node
        bootstrap_node(str(mock_node.id), "10.0.1.50")

    assert call_order == ["pillar", "ansible"]


def test_write_pillar_file_creates_correct_content(tmp_path):
    from fleet_platform.workers.ansible_tasks import _write_pillar_file
    _write_pillar_file(
        pillar_dir=str(tmp_path),
        minion_id="mac-01.local",
        ingest_url="http://10.0.0.1:8000/api/v1/ingest",
        node_token="mytoken123",
    )
    sls = (tmp_path / "mac-01.local.sls").read_text()
    assert "mytoken123" in sls
    assert "fleet_platform" in sls
    assert "http://10.0.0.1:8000/api/v1/ingest" in sls
```

- [ ] **Step 2: Run to confirm they fail**

```bash
source .venv/bin/activate && pytest tests/unit/test_ansible_tasks.py -v 2>&1 | tail -10
```
Expected: ImportError.

- [ ] **Step 3: Implement ansible_tasks.py**

```python
# fleet_platform/workers/ansible_tasks.py
"""
Celery tasks for Ansible-based node bootstrap.
"""
import os
import uuid as _uuid
from pathlib import Path

import ansible_runner
from sqlalchemy import select

from fleet_platform.core.config import settings
from fleet_platform.db.session import get_sync_db
from fleet_platform.models.node import Node
from fleet_platform.models.platform_setting import PlatformSetting
from fleet_platform.services.ssh_keypair import get_controller_pubkey
from fleet_platform.workers.celery_app import celery_app

_PLAYBOOKS_DIR = Path(__file__).parent.parent.parent / "playbooks"
_DEFAULT_PILLAR_DIR = Path("/srv/salt/pillar")
_DEFAULT_KRI_DIR = Path.home() / ".kri"


def _get_bootstrap_settings(db) -> tuple[str, str, str, str, str]:
    """Returns (salt_master, ssh_user, ssh_password, priv_key_path, pubkey)."""
    from fleet_platform.services.platform_settings_svc import (
        SSH_PASSWORD, SSH_USERNAME, SALT_MASTER,
        CONTROLLER_PRIVKEY_PATH, CONTROLLER_PUBKEY_PATH,
        _fernet,
    )

    def _get(key: str) -> str:
        row = db.execute(select(PlatformSetting).where(PlatformSetting.key == key)).scalar_one_or_none()
        if row is None:
            return ""
        if row.is_encrypted and row.value:
            return _fernet().decrypt(row.value.encode()).decode()
        return row.value or ""

    salt_master = _get(SALT_MASTER) or "localhost"
    ssh_user = _get(SSH_USERNAME) or "admin"
    ssh_password = _get(SSH_PASSWORD)
    priv_path = _get(CONTROLLER_PRIVKEY_PATH) or str(_DEFAULT_KRI_DIR / "id_rsa")
    pub_path = _get(CONTROLLER_PUBKEY_PATH) or str(_DEFAULT_KRI_DIR / "id_rsa.pub")
    pubkey = get_controller_pubkey(pub_path) or ""
    return salt_master, ssh_user, ssh_password, priv_path, pubkey


def _write_pillar_file(
    pillar_dir: str,
    minion_id: str,
    ingest_url: str,
    node_token: str,
) -> None:
    """Write /srv/salt/pillar/<minion_id>.sls with the node's token."""
    pillar_path = Path(pillar_dir)
    pillar_path.mkdir(parents=True, exist_ok=True)

    sls_content = f"""# Auto-generated by kri bootstrap — do not edit manually
fleet_platform:
  ingest_url: {ingest_url}
  node_token: {node_token}
"""
    (pillar_path / f"{minion_id}.sls").write_text(sls_content)

    # Ensure top.sls includes this minion
    top_path = pillar_path / "top.sls"
    if top_path.exists():
        existing = top_path.read_text()
        if minion_id not in existing:
            # Append entry under base
            top_path.write_text(existing.rstrip() + f"\n  '{minion_id}':\n    - {minion_id}\n")
    else:
        top_path.write_text(f"base:\n  '{minion_id}':\n    - {minion_id}\n")


@celery_app.task(
    name="fleet_platform.workers.ansible_tasks.bootstrap_node",
    bind=True,
    max_retries=0,  # bootstrap is not retried automatically
    queue="maintenance",
)
def bootstrap_node(self, node_id: str, target_ip: str) -> dict:
    """
    Run the bootstrap_mac_mini.yml playbook against a single Mac Mini.
    Updates node.bootstrap_status throughout.
    """
    import tempfile

    node_uuid = _uuid.UUID(node_id)

    with get_sync_db() as db:
        node = db.execute(select(Node).where(Node.id == node_uuid)).scalar_one_or_none()
        if not node:
            return {"status": "error", "reason": "node_not_found"}

        node.bootstrap_status = "bootstrapping"
        node.bootstrap_ip = target_ip
        node.bootstrap_error = None
        db.commit()

        salt_master, ssh_user, ssh_password, priv_key_path, controller_pubkey = \
            _get_bootstrap_settings(db)

    # Write pillar before Ansible runs so the minion has its token on first connect
    ingest_url = f"http://{salt_master}:8000/api/v1/ingest"
    # Decode the stored token hash is not useful here — we need the raw token.
    # The raw token is NOT stored after registration (only the hash is).
    # So we generate a fresh token here and update the node's hash.
    import secrets
    from fleet_platform.core.auth import hash_password as hp
    raw_token = secrets.token_urlsafe(32)

    _write_pillar_file(
        pillar_dir=str(_DEFAULT_PILLAR_DIR),
        minion_id=node.minion_id,
        ingest_url=ingest_url,
        node_token=raw_token,
    )

    # Update node token hash with the new raw token
    with get_sync_db() as db:
        node = db.execute(select(Node).where(Node.id == node_uuid)).scalar_one()
        node.node_token_hash = hp(raw_token)
        db.commit()

    # Run Ansible in a temp directory
    with tempfile.TemporaryDirectory(prefix="kri-bootstrap-") as tmpdir:
        env = {
            "TARGET_HOST": target_ip,
            "ANSIBLE_USER": ssh_user,
            "ANSIBLE_PASSWORD": ssh_password,
        }

        result = ansible_runner.run(
            private_data_dir=tmpdir,
            playbook=str(_PLAYBOOKS_DIR / "bootstrap_mac_mini.yml"),
            inventory=str(_PLAYBOOKS_DIR / "inventory" / "dynamic.py"),
            extravars={
                "salt_master_address": salt_master,
                "minion_id": node.minion_id,
                "controller_pubkey": controller_pubkey,
            },
            envvars=env,
            quiet=False,
            rotate_artifacts=1,
        )

    with get_sync_db() as db:
        node = db.execute(select(Node).where(Node.id == node_uuid)).scalar_one()
        if result.status == "successful" and result.rc == 0:
            node.bootstrap_status = "completed"
            node.bootstrap_error = None
        else:
            node.bootstrap_status = "failed"
            node.bootstrap_error = f"ansible-runner rc={result.rc} status={result.status}"
        db.commit()

    return {
        "status": result.status,
        "rc": result.rc,
        "node_id": node_id,
    }
```

- [ ] **Step 4: Register in celery_app.py**

Add `"fleet_platform.workers.ansible_tasks"` to the `include` list.

- [ ] **Step 5: Run tests**

```bash
source .venv/bin/activate && pytest tests/unit/test_ansible_tasks.py -v 2>&1 | tail -10
```
Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add fleet_platform/workers/ansible_tasks.py fleet_platform/workers/celery_app.py \
  tests/unit/test_ansible_tasks.py
git commit -m "feat(P11): ansible bootstrap_node Celery task with pillar pre-write"
```

---

## Task 5: API Routes — Bootstrap + Platform Settings

**Files:**
- Create: `fleet_platform/api/routes/ansible.py`
- Create: `fleet_platform/api/routes/platform_settings.py`
- Create: `fleet_platform/schemas/ansible.py`
- Modify: `fleet_platform/api/main.py`
- Test: `tests/integration/test_ansible_api.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/integration/test_ansible_api.py
import pytest
from httpx import AsyncClient


async def test_get_settings_requires_admin(viewer_client: AsyncClient):
    r = await viewer_client.get("/api/v1/settings")
    assert r.status_code == 403


async def test_admin_can_set_and_get_settings(admin_client: AsyncClient):
    r = await admin_client.put("/api/v1/settings", json={
        "salt_master_address": "10.0.0.1",
        "ssh_bootstrap_username": "localadmin",
        "ssh_bootstrap_password": "secret123",
    })
    assert r.status_code == 200

    r2 = await admin_client.get("/api/v1/settings")
    assert r2.status_code == 200
    data = r2.json()
    assert data["salt_master_address"] == "10.0.0.1"
    assert data["ssh_bootstrap_username"] == "localadmin"
    # Password must NOT be returned in plaintext
    assert "ssh_bootstrap_password" not in data or data.get("ssh_bootstrap_password") is None


async def test_controller_pubkey_returned(admin_client: AsyncClient):
    r = await admin_client.get("/api/v1/settings")
    assert r.status_code == 200
    data = r.json()
    # controller_pubkey may be None if keypair not generated yet — either is fine
    assert "controller_pubkey" in data


async def test_bootstrap_requires_operator(viewer_client: AsyncClient):
    r = await viewer_client.post("/api/v1/ansible/bootstrap", json={
        "minion_id": "test-node.local",
        "target_ip": "10.0.1.50",
    })
    assert r.status_code == 403
```

- [ ] **Step 2: Run to confirm they fail**

```bash
source .venv/bin/activate && pytest tests/integration/test_ansible_api.py -v 2>&1 | tail -10
```
Expected: 404 (routes not registered).

- [ ] **Step 3: Create schemas**

```python
# fleet_platform/schemas/ansible.py
import uuid
from datetime import datetime
from pydantic import BaseModel


class BootstrapRequest(BaseModel):
    minion_id: str
    target_ip: str


class BootstrapResponse(BaseModel):
    node_id: uuid.UUID
    minion_id: str
    job_id: str
    bootstrap_status: str
    message: str


class PlatformSettingsUpdate(BaseModel):
    salt_master_address: str | None = None
    ssh_bootstrap_username: str | None = None
    ssh_bootstrap_password: str | None = None


class PlatformSettingsResponse(BaseModel):
    salt_master_address: str | None
    ssh_bootstrap_username: str | None
    ssh_bootstrap_password: None = None  # never returned
    controller_pubkey: str | None
```

- [ ] **Step 4: Create platform_settings route**

```python
# fleet_platform/api/routes/platform_settings.py
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.api.deps import get_db
from fleet_platform.core.auth import require_role
from fleet_platform.schemas.ansible import PlatformSettingsResponse, PlatformSettingsUpdate
from fleet_platform.services.platform_settings_svc import (
    SALT_MASTER, SSH_USERNAME, SSH_PASSWORD,
    get_setting, set_setting,
)
from fleet_platform.services.ssh_keypair import ensure_controller_keypair, get_controller_pubkey

router = APIRouter(prefix="/api/v1/settings")


@router.get("", response_model=PlatformSettingsResponse)
async def get_settings(
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("admin")),
):
    ensure_controller_keypair()  # generate if not present
    return PlatformSettingsResponse(
        salt_master_address=await get_setting(db, SALT_MASTER),
        ssh_bootstrap_username=await get_setting(db, SSH_USERNAME),
        ssh_bootstrap_password=None,
        controller_pubkey=get_controller_pubkey(),
    )


@router.put("", response_model=PlatformSettingsResponse)
async def update_settings(
    payload: PlatformSettingsUpdate,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("admin")),
):
    ensure_controller_keypair()
    if payload.salt_master_address is not None:
        await set_setting(db, SALT_MASTER, payload.salt_master_address)
    if payload.ssh_bootstrap_username is not None:
        await set_setting(db, SSH_USERNAME, payload.ssh_bootstrap_username)
    if payload.ssh_bootstrap_password is not None:
        await set_setting(db, SSH_PASSWORD, payload.ssh_bootstrap_password, encrypt=True)
    return PlatformSettingsResponse(
        salt_master_address=await get_setting(db, SALT_MASTER),
        ssh_bootstrap_username=await get_setting(db, SSH_USERNAME),
        ssh_bootstrap_password=None,
        controller_pubkey=get_controller_pubkey(),
    )
```

- [ ] **Step 5: Create ansible route**

```python
# fleet_platform/api/routes/ansible.py
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.api.deps import get_db
from fleet_platform.core.auth import require_role
from fleet_platform.core.auth import hash_password
from fleet_platform.models.node import Node
from fleet_platform.schemas.ansible import BootstrapRequest, BootstrapResponse
from fleet_platform.workers.ansible_tasks import bootstrap_node

import secrets

router = APIRouter(prefix="/api/v1/ansible")


@router.post("/bootstrap", response_model=BootstrapResponse, status_code=202)
async def bootstrap(
    payload: BootstrapRequest,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_role("operator", "admin")),
):
    # Upsert node record (create if not exists, or re-bootstrap if failed)
    result = await db.execute(
        select(Node).where(Node.minion_id == payload.minion_id)
    )
    node = result.scalar_one_or_none()

    if node and node.bootstrap_status == "bootstrapping":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Node is already being bootstrapped",
        )

    placeholder_token = secrets.token_urlsafe(32)

    if node is None:
        from datetime import UTC, datetime
        node = Node(
            minion_id=payload.minion_id,
            hostname=payload.minion_id.split(".")[0],
            ip_address=payload.target_ip,
            status="unknown",
            drift_score=0,
            node_token_hash=hash_password(placeholder_token),
            first_seen_at=datetime.now(UTC),
            bootstrap_status="pending",
            bootstrap_ip=payload.target_ip,
        )
        db.add(node)
        await db.commit()
        await db.refresh(node)
    else:
        node.bootstrap_status = "pending"
        node.bootstrap_ip = payload.target_ip
        await db.commit()

    # Queue the bootstrap task
    task = bootstrap_node.delay(str(node.id), payload.target_ip)

    return BootstrapResponse(
        node_id=node.id,
        minion_id=node.minion_id,
        job_id=task.id,
        bootstrap_status="pending",
        message="Bootstrap queued. Salt minion will appear in fleet when complete.",
    )


@router.get("/bootstrap/{node_id}/status")
async def bootstrap_status(
    node_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("operator", "admin")),
):
    result = await db.execute(select(Node).where(Node.id == node_id))
    node = result.scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    return {
        "node_id": str(node.id),
        "minion_id": node.minion_id,
        "bootstrap_status": node.bootstrap_status,
        "bootstrap_ip": node.bootstrap_ip,
        "bootstrap_error": node.bootstrap_error,
    }
```

- [ ] **Step 6: Register routers in main.py**

```python
from fleet_platform.api.routes import (
    health, auth, nodes, ingest, fleet, groups, search,
    baselines, drift, executions, sbom, ansible, platform_settings
)

# In create_app():
app.include_router(ansible.router, tags=["ansible"])
app.include_router(platform_settings.router, tags=["settings"])
```

- [ ] **Step 7: Run tests**

```bash
source .venv/bin/activate && pytest tests/integration/test_ansible_api.py -v 2>&1 | tail -15
```
Expected: 4 passed.

```bash
source .venv/bin/activate && pytest tests/ -q --no-header 2>&1 | tail -5
```
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add fleet_platform/api/routes/ansible.py fleet_platform/api/routes/platform_settings.py \
  fleet_platform/schemas/ansible.py fleet_platform/api/main.py \
  tests/integration/test_ansible_api.py
git commit -m "feat(P11): bootstrap API + platform settings CRUD — POST /api/v1/ansible/bootstrap"
```

---

## Task 6: Frontend — Settings Page + Bootstrap Flow

**Files:**
- Create: `frontend/src/api/ansible.ts`
- Create: `frontend/src/pages/SettingsPage.tsx`
- Create: `frontend/src/pages/BootstrapModal.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/Layout/Sidebar.tsx`
- Modify: `frontend/src/pages/FleetDashboard.tsx`

- [ ] **Step 1: Create ansible API client**

```typescript
// frontend/src/api/ansible.ts
import { api } from './client'

export interface PlatformSettings {
  salt_master_address: string | null
  ssh_bootstrap_username: string | null
  ssh_bootstrap_password: null
  controller_pubkey: string | null
}

export interface BootstrapResponse {
  node_id: string
  minion_id: string
  job_id: string
  bootstrap_status: string
  message: string
}

export interface BootstrapStatus {
  node_id: string
  minion_id: string
  bootstrap_status: 'pending' | 'bootstrapping' | 'completed' | 'failed'
  bootstrap_ip: string | null
  bootstrap_error: string | null
}

export const ansibleApi = {
  getSettings: () => api.get<PlatformSettings>('/api/v1/settings'),
  updateSettings: (payload: {
    salt_master_address?: string
    ssh_bootstrap_username?: string
    ssh_bootstrap_password?: string
  }) => api.put<PlatformSettings>('/api/v1/settings', payload),
  bootstrap: (minion_id: string, target_ip: string) =>
    api.post<BootstrapResponse>('/api/v1/ansible/bootstrap', { minion_id, target_ip }),
  bootstrapStatus: (nodeId: string) =>
    api.get<BootstrapStatus>(`/api/v1/ansible/bootstrap/${nodeId}/status`),
}
```

- [ ] **Step 2: Create SettingsPage**

```tsx
// frontend/src/pages/SettingsPage.tsx
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { ansibleApi } from '../api/ansible'
import { useToastStore } from '../stores/toastStore'

export function SettingsPage() {
  const qc = useQueryClient()
  const toast = useToastStore((s) => s.add)
  const [master, setMaster] = useState('')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)

  const { data, isLoading } = useQuery({
    queryKey: ['settings'],
    queryFn: ansibleApi.getSettings,
    onSuccess: (d) => {
      if (d.salt_master_address) setMaster(d.salt_master_address)
      if (d.ssh_bootstrap_username) setUsername(d.ssh_bootstrap_username)
    },
  })

  const saveMutation = useMutation({
    mutationFn: () => ansibleApi.updateSettings({
      salt_master_address: master || undefined,
      ssh_bootstrap_username: username || undefined,
      ssh_bootstrap_password: password || undefined,
    }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['settings'] })
      toast('Settings saved')
      setPassword('')
    },
    onError: (e: Error) => toast(e.message, 'error'),
  })

  if (isLoading) return <div className="p-6 text-gray-500">Loading…</div>

  return (
    <div className="space-y-8 max-w-2xl">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Settings</h1>
        <p className="text-gray-500 mt-1">Configure Salt master and SSH bootstrap credentials.</p>
      </div>

      {/* Salt Master */}
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-6 space-y-4">
        <h2 className="text-base font-semibold text-gray-900">Salt Master</h2>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Master address (LAN IP or DNS)
          </label>
          <input
            type="text"
            value={master}
            onChange={(e) => setMaster(e.target.value)}
            placeholder="10.0.0.1 or salt.fleet.local"
            className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm text-gray-900 focus:outline-none focus:border-brand-600"
          />
          <p className="text-xs text-gray-400 mt-1">Salt minions will point to this address.</p>
        </div>
      </div>

      {/* SSH Bootstrap credentials */}
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-6 space-y-4">
        <h2 className="text-base font-semibold text-gray-900">SSH Bootstrap Credentials</h2>
        <p className="text-sm text-gray-500">
          Used only for initial bootstrap via Ansible. All Mac Minis must share these credentials.
          After bootstrap, kri uses the controller SSH key for all future connections.
        </p>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">macOS admin username</label>
          <input
            type="text"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            placeholder="localadmin"
            className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm text-gray-900 focus:outline-none focus:border-brand-600"
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            macOS admin password
            <span className="ml-2 text-xs font-normal text-gray-400">(stored encrypted, not shown after save)</span>
          </label>
          <div className="relative">
            <input
              type={showPassword ? 'text' : 'password'}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Leave blank to keep existing"
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm text-gray-900 focus:outline-none focus:border-brand-600 pr-16"
            />
            <button
              type="button"
              onClick={() => setShowPassword(!showPassword)}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-xs text-gray-400 hover:text-gray-600"
            >
              {showPassword ? 'Hide' : 'Show'}
            </button>
          </div>
        </div>
      </div>

      {/* Controller SSH public key */}
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-6 space-y-3">
        <h2 className="text-base font-semibold text-gray-900">Controller SSH Public Key</h2>
        <p className="text-sm text-gray-500">
          This key is deployed to all Mac Minis during bootstrap. Add it to existing nodes manually if needed.
        </p>
        {data?.controller_pubkey ? (
          <div className="relative">
            <pre className="text-xs font-mono bg-gray-50 border border-gray-200 rounded-lg p-3 overflow-x-auto text-gray-700 whitespace-pre-wrap break-all">
              {data.controller_pubkey}
            </pre>
            <button
              onClick={() => { navigator.clipboard.writeText(data.controller_pubkey!); toast('Copied') }}
              className="absolute top-2 right-2 text-xs text-gray-400 hover:text-gray-600 bg-white border border-gray-200 rounded px-2 py-0.5"
            >
              Copy
            </button>
          </div>
        ) : (
          <p className="text-sm text-amber-700 bg-amber-50 border border-amber-200 rounded-lg p-3">
            No keypair generated yet. Save settings once to generate the controller keypair.
          </p>
        )}
      </div>

      <div className="flex justify-end">
        <button
          onClick={() => saveMutation.mutate()}
          disabled={saveMutation.isPending}
          className="px-6 py-2.5 bg-brand-600 text-white rounded-lg font-medium hover:bg-brand-700 disabled:opacity-50 shadow-sm"
        >
          {saveMutation.isPending ? 'Saving…' : 'Save Settings'}
        </button>
      </div>
    </div>
  )
}
```

- [ ] **Step 3: Create BootstrapModal**

```tsx
// frontend/src/pages/BootstrapModal.tsx
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ansibleApi } from '../api/ansible'
import { useToastStore } from '../stores/toastStore'

interface Props {
  onClose: () => void
}

const STATUS_LABEL: Record<string, { label: string; colour: string }> = {
  pending:      { label: 'Queued',       colour: 'text-gray-500' },
  bootstrapping:{ label: 'Running…',     colour: 'text-brand-600' },
  completed:    { label: 'Done ✓',       colour: 'text-emerald-700' },
  failed:       { label: 'Failed',       colour: 'text-red-700' },
}

export function BootstrapModal({ onClose }: Props) {
  const [minionId, setMinionId] = useState('')
  const [targetIp, setTargetIp] = useState('')
  const [nodeId, setNodeId] = useState<string | null>(null)
  const toast = useToastStore((s) => s.add)
  const qc = useQueryClient()

  const bootstrapMutation = useMutation({
    mutationFn: () => ansibleApi.bootstrap(minionId, targetIp),
    onSuccess: (data) => {
      setNodeId(data.node_id)
      toast('Bootstrap started')
    },
    onError: (e: Error) => toast(e.message, 'error'),
  })

  const { data: statusData } = useQuery({
    queryKey: ['bootstrap-status', nodeId],
    queryFn: () => ansibleApi.bootstrapStatus(nodeId!),
    enabled: !!nodeId,
    refetchInterval: (query) => {
      const s = query.state.data?.bootstrap_status
      return (s === 'pending' || s === 'bootstrapping') ? 3000 : false
    },
    onSuccess: (d) => {
      if (d.bootstrap_status === 'completed') {
        qc.invalidateQueries({ queryKey: ['nodes'] })
        qc.invalidateQueries({ queryKey: ['fleet-overview'] })
      }
    },
  })

  const status = statusData?.bootstrap_status
  const { label, colour } = STATUS_LABEL[status ?? 'pending'] ?? STATUS_LABEL.pending

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-white rounded-2xl shadow-2xl p-6 w-full max-w-md mx-4">
        <div className="flex items-center justify-between mb-6">
          <h2 className="text-lg font-bold text-gray-900">Bootstrap Mac Mini</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl">×</button>
        </div>

        {!nodeId ? (
          <form onSubmit={(e) => { e.preventDefault(); bootstrapMutation.mutate() }} className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Minion ID <span className="text-gray-400 font-normal">(hostname, e.g. mac-mini-01)</span>
              </label>
              <input
                required
                value={minionId}
                onChange={(e) => setMinionId(e.target.value)}
                placeholder="mac-mini-01"
                className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm text-gray-900 focus:outline-none focus:border-brand-600"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">IP address</label>
              <input
                required
                value={targetIp}
                onChange={(e) => setTargetIp(e.target.value)}
                placeholder="10.0.1.11"
                className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm text-gray-900 focus:outline-none focus:border-brand-600"
              />
            </div>
            <p className="text-xs text-gray-500 bg-amber-50 border border-amber-200 rounded-lg p-3">
              Make sure Remote Login (SSH) is enabled on the Mac Mini before running bootstrap.
            </p>
            <div className="flex gap-3 pt-2">
              <button type="button" onClick={onClose}
                className="flex-1 py-2.5 border border-gray-300 text-gray-700 rounded-lg text-sm font-medium hover:bg-gray-50">
                Cancel
              </button>
              <button type="submit" disabled={bootstrapMutation.isPending}
                className="flex-1 py-2.5 bg-brand-600 text-white rounded-lg text-sm font-medium hover:bg-brand-700 disabled:opacity-50">
                {bootstrapMutation.isPending ? 'Starting…' : 'Bootstrap'}
              </button>
            </div>
          </form>
        ) : (
          <div className="space-y-4">
            <div className="flex items-center gap-3 p-4 bg-gray-50 rounded-xl border border-gray-200">
              <div className={`text-sm font-semibold ${colour}`}>{label}</div>
              <div className="text-sm text-gray-600 flex-1">{minionId} @ {targetIp}</div>
              {(status === 'pending' || status === 'bootstrapping') && (
                <div className="w-4 h-4 border-2 border-brand-600 border-t-transparent rounded-full animate-spin" />
              )}
            </div>

            {statusData?.bootstrap_error && (
              <div className="p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700 font-mono">
                {statusData.bootstrap_error}
              </div>
            )}

            {status === 'completed' && (
              <p className="text-sm text-emerald-700 bg-emerald-50 border border-emerald-200 rounded-lg p-3">
                Bootstrap complete. The node will appear in the fleet dashboard once the Salt minion connects and reports its grains.
              </p>
            )}

            <button
              onClick={onClose}
              className="w-full py-2.5 border border-gray-300 text-gray-700 rounded-lg text-sm font-medium hover:bg-gray-50"
            >
              {status === 'completed' || status === 'failed' ? 'Close' : 'Close (runs in background)'}
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
```

- [ ] **Step 4: Add Bootstrap button to FleetDashboard**

In `FleetDashboard.tsx`, add:

```tsx
import { useState } from 'react'
import { BootstrapModal } from './BootstrapModal'

// Inside FleetDashboard component body, add:
const [showBootstrap, setShowBootstrap] = useState(false)

// Add Bootstrap button next to the heading:
<div className="flex items-center justify-between">
  <h1 className="text-2xl font-bold text-gray-900">Fleet Dashboard</h1>
  <button
    onClick={() => setShowBootstrap(true)}
    className="px-4 py-2 bg-brand-600 text-white text-sm font-medium rounded-lg hover:bg-brand-700 shadow-sm"
  >
    + Bootstrap Node
  </button>
</div>

// At the end of the JSX return, before closing div:
{showBootstrap && <BootstrapModal onClose={() => setShowBootstrap(false)} />}
```

- [ ] **Step 5: Add Settings to Sidebar and App routing**

In `Sidebar.tsx`, the links array already includes `{ to: '/settings', label: 'Settings', icon: '⚙' }` — add it if missing.

In `App.tsx`:
```tsx
import { SettingsPage } from './pages/SettingsPage'
// Inside Routes:
<Route path="/settings" element={<SettingsPage />} />
```

- [ ] **Step 6: TypeScript check**

```bash
cd /home/dk/Documents/git/kri/frontend && npx tsc --noEmit 2>&1 | tail -10
```
Expected: zero errors.

- [ ] **Step 7: Commit**

```bash
cd /home/dk/Documents/git/kri
git add frontend/src/api/ansible.ts frontend/src/pages/SettingsPage.tsx \
  frontend/src/pages/BootstrapModal.tsx frontend/src/pages/FleetDashboard.tsx \
  frontend/src/App.tsx frontend/src/components/Layout/Sidebar.tsx
git commit -m "feat(P11): Settings page + Bootstrap node modal with live status polling"
```

---

## Task 7: Full Test Suite + Smoke Test

- [ ] **Step 1: Run all backend tests**

```bash
source .venv/bin/activate && python -m pytest tests/ -q --no-header 2>&1 | tail -5
```
Expected: all pass (170+ tests).

- [ ] **Step 2: TypeScript + production build**

```bash
cd /home/dk/Documents/git/kri/frontend && npx tsc --noEmit && npm run build 2>&1 | tail -3
```
Expected: `✓ built`.

- [ ] **Step 3: Smoke test the API**

Start the backend:
```bash
source .venv/bin/activate && uvicorn fleet_platform.api.main:app --port 8000 &
sleep 2
```

Test settings endpoint:
```bash
TOKEN=$(curl -s -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@fleet.local","password":"changeme123"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

curl -s http://localhost:8000/api/v1/settings \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```
Expected: JSON with `salt_master_address`, `ssh_bootstrap_username`, `controller_pubkey` fields.

```bash
curl -s -X PUT http://localhost:8000/api/v1/settings \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"salt_master_address":"10.0.0.1","ssh_bootstrap_username":"localadmin","ssh_bootstrap_password":"test123"}' \
  | python3 -m json.tool
```
Expected: settings returned, `ssh_bootstrap_password` is null.

- [ ] **Step 4: Final commit + merge**

```bash
git log --oneline -8
```

---

## Self-Review Checklist

**Spec coverage:**
- [x] Same SSH username/password for all nodes → stored once in `platform_settings` — Task 5
- [x] Fixed LAN IP or DNS for Salt master → `SALT_MASTER` setting — Task 5
- [x] Homebrew installation (not assumed present) → Playbook Task 3 (`brew_stat` check + install)
- [x] SSH auth handled with `become`/sudo — Playbook Task 3 (`ansible_become: true`)
- [x] `StrictHostKeyChecking=no` for first connections — Playbook `ansible_ssh_common_args`
- [x] Basic bootstrapping only (no OS hardening) — Playbook Tasks 3
- [x] Controller SSH keypair generated at `~/.kri/` — Task 2 (`ssh_keypair.py`)
- [x] Controller pubkey deployed to Mac Minis — Playbook `authorized_key` task
- [x] Pillar written before Ansible runs — `ansible_tasks.py` `_write_pillar_file` called first
- [x] Node token refreshed during bootstrap — new random token generated + hash updated
- [x] Bootstrap status lifecycle: pending → bootstrapping → completed/failed — Tasks 1, 4
- [x] Bootstrap API (POST /api/v1/ansible/bootstrap) — Task 5
- [x] Frontend Settings page with public key display + copy — Task 6
- [x] Frontend Bootstrap modal with live polling — Task 6
- [x] Fleet Dashboard "+ Bootstrap Node" button — Task 6
- [x] Tests for settings service, SSH keypair, Celery task, API routes — Tasks 2, 4, 5

**Type consistency check:**
- `_get_bootstrap_settings()` returns `(str, str, str, str, str)` — used in `bootstrap_node()` ✓
- `_write_pillar_file(pillar_dir, minion_id, ingest_url, node_token)` — called with correct args ✓
- `BootstrapResponse` fields match `bootstrap` endpoint return ✓
- `ansibleApi.bootstrapStatus(nodeId)` → `GET /api/v1/ansible/bootstrap/{nodeId}/status` ✓
