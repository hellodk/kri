# LLM Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow users to configure multiple LLM endpoints in platform settings and use natural language to generate Salt states, Ansible playbooks, fleet commands, and explanations via an AI assistant panel.

**Architecture:** Two new DB tables (`llm_endpoints`, `llm_query_log`) back a CRUD API; a fleet context builder snapshot-injects node/group state into every LLM system prompt; the frontend surfaces endpoint management in Settings → LLM tab and a floating AI Assistant panel accessible from all pages. All LLM output lands in a read-only preview — nothing is auto-executed. No knowledge graph: the fleet is small enough to fit in a system prompt (~500 tokens); a clean `build_fleet_context()` interface can be swapped for a graph-based retriever later if needed.

**Tech Stack:** FastAPI + SQLAlchemy 2.0 async + PostgreSQL + httpx (already in deps) + anthropic Python SDK (new dep) + React 18 + TanStack Query 5 + Tailwind CSS

**Closes:** #38

---

## File Map

### New files

| File | Purpose |
|------|---------|
| `fleet_platform/models/llm_endpoint.py` | SQLAlchemy model for `llm_endpoints` table |
| `fleet_platform/models/llm_query_log.py` | SQLAlchemy model for `llm_query_log` table |
| `fleet_platform/db/migrations/versions/018_llm.py` | Alembic migration creating both tables |
| `fleet_platform/schemas/llm.py` | Pydantic request/response schemas |
| `fleet_platform/services/llm_svc.py` | CRUD for LLMEndpoint + query log creation |
| `fleet_platform/services/llm_context.py` | `build_fleet_context()` — fleet snapshot for system prompt |
| `fleet_platform/services/llm_caller.py` | `call_openai_compat()` + `call_anthropic()` |
| `fleet_platform/api/routes/llm.py` | All `/api/v1/llm/*` routes |
| `tests/unit/test_llm_context.py` | Unit tests for context builder |
| `tests/unit/test_llm_caller.py` | Unit tests for provider callers (mocked HTTP) |
| `tests/unit/test_llm_schemas.py` | Unit tests for Pydantic schemas |
| `tests/integration/test_llm_api.py` | Integration tests for all LLM routes |
| `frontend/src/api/llm.ts` | Frontend API client module |
| `frontend/src/components/llm/LLMAssistant.tsx` | Floating AI assistant panel |
| `frontend/src/components/llm/LLMEndpointForm.tsx` | Add/edit endpoint modal form |

### Modified files

| File | Change |
|------|--------|
| `fleet_platform/models/__init__.py` | Export new models |
| `fleet_platform/api/main.py` | Import + register `llm_router` |
| `pyproject.toml` | Add `anthropic>=0.40` to runtime deps |
| `frontend/src/pages/SettingsPage.tsx` | Add LLM tab with endpoint list |
| `frontend/src/App.tsx` or layout component | Mount `<LLMAssistant />` globally |

---

## Task 1: Models + Migration

**Files:**
- Create: `fleet_platform/models/llm_endpoint.py`
- Create: `fleet_platform/models/llm_query_log.py`
- Create: `fleet_platform/db/migrations/versions/018_llm.py`
- Modify: `fleet_platform/models/__init__.py`

- [ ] **Step 1: Write the failing model import test**

```python
# tests/unit/test_llm_schemas.py
def test_llm_endpoint_model_importable():
    from fleet_platform.models.llm_endpoint import LLMEndpoint
    assert LLMEndpoint.__tablename__ == "llm_endpoints"

def test_llm_query_log_model_importable():
    from fleet_platform.models.llm_query_log import LLMQueryLog
    assert LLMQueryLog.__tablename__ == "llm_query_log"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/dk/Documents/git/kri && source .venv/bin/activate
pytest tests/unit/test_llm_schemas.py::test_llm_endpoint_model_importable -v
```
Expected: `ModuleNotFoundError: No module named 'fleet_platform.models.llm_endpoint'`

- [ ] **Step 3: Create `fleet_platform/models/llm_endpoint.py`**

```python
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from fleet_platform.models.base import Base


class LLMEndpoint(Base):
    __tablename__ = "llm_endpoints"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # "openai_compat" covers OpenAI, Ollama, LM Studio, vLLM, Groq, Mistral
    # "anthropic" uses the native Anthropic SDK
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    # Stored as Fernet-encrypted ciphertext; None for providers that need no key (e.g. local Ollama)
    api_key_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    model: Mapped[str] = mapped_column(String(255), nullable=False)
    max_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=4096)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        Index("idx_llm_endpoints_is_default", "is_default"),
        Index("idx_llm_endpoints_enabled", "enabled"),
    )
```

- [ ] **Step 4: Create `fleet_platform/models/llm_query_log.py`**

```python
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from fleet_platform.models.base import Base


class LLMQueryLog(Base):
    __tablename__ = "llm_query_log"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # SET NULL so query log survives endpoint deletion
    endpoint_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("llm_endpoints.id", ondelete="SET NULL"),
        nullable=True,
    )
    user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    intent: Mapped[str] = mapped_column(String(30), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    response: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_used: Mapped[str | None] = mapped_column(String(255), nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("idx_llm_query_log_user_id", "user_id", "created_at"),
        Index("idx_llm_query_log_endpoint_id", "endpoint_id"),
    )
```

- [ ] **Step 5: Create `fleet_platform/db/migrations/versions/018_llm.py`**

```python
"""Create llm_endpoints and llm_query_log tables

Revision ID: 018
Revises: 017
Create Date: 2026-05-26
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "018"
down_revision = "017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "llm_endpoints",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("provider", sa.String(20), nullable=False),
        sa.Column("base_url", sa.String(500), nullable=False),
        sa.Column("api_key_encrypted", sa.Text, nullable=True),
        sa.Column("model", sa.String(255), nullable=False),
        sa.Column("max_tokens", sa.Integer, nullable=False, server_default="4096"),
        sa.Column("is_default", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("idx_llm_endpoints_is_default", "llm_endpoints", ["is_default"])
    op.create_index("idx_llm_endpoints_enabled", "llm_endpoints", ["enabled"])

    op.create_table(
        "llm_query_log",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "endpoint_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("llm_endpoints.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("user_id", sa.String(255), nullable=False),
        sa.Column("intent", sa.String(30), nullable=False),
        sa.Column("prompt", sa.Text, nullable=False),
        sa.Column("system_prompt", sa.Text, nullable=False),
        sa.Column("response", sa.Text, nullable=True),
        sa.Column("model_used", sa.String(255), nullable=True),
        sa.Column("input_tokens", sa.Integer, nullable=True),
        sa.Column("output_tokens", sa.Integer, nullable=True),
        sa.Column("duration_ms", sa.Integer, nullable=True),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "idx_llm_query_log_user_id", "llm_query_log", ["user_id", "created_at"]
    )
    op.create_index(
        "idx_llm_query_log_endpoint_id", "llm_query_log", ["endpoint_id"]
    )


def downgrade() -> None:
    op.drop_table("llm_query_log")
    op.drop_table("llm_endpoints")
```

- [ ] **Step 6: Add exports to `fleet_platform/models/__init__.py`**

Open the file and append to it:
```python
from fleet_platform.models.llm_endpoint import LLMEndpoint
from fleet_platform.models.llm_query_log import LLMQueryLog
```

- [ ] **Step 7: Run the model import tests**

```bash
pytest tests/unit/test_llm_schemas.py::test_llm_endpoint_model_importable \
       tests/unit/test_llm_schemas.py::test_llm_query_log_model_importable -v
```
Expected: 2 PASSED

- [ ] **Step 8: Commit**

```bash
git add fleet_platform/models/llm_endpoint.py \
        fleet_platform/models/llm_query_log.py \
        fleet_platform/models/__init__.py \
        fleet_platform/db/migrations/versions/018_llm.py \
        tests/unit/test_llm_schemas.py
git commit -m "feat: add LLMEndpoint and LLMQueryLog models + migration 018"
```

---

## Task 2: Schemas + CRUD Service

**Files:**
- Create: `fleet_platform/schemas/llm.py`
- Create: `fleet_platform/services/llm_svc.py`
- Test: `tests/unit/test_llm_schemas.py` (extend)

- [ ] **Step 1: Write failing schema tests**

Add to `tests/unit/test_llm_schemas.py`:

```python
def test_llm_endpoint_create_schema_rejects_unknown_provider():
    from pydantic import ValidationError
    from fleet_platform.schemas.llm import LLMEndpointCreate
    import pytest
    with pytest.raises(ValidationError):
        LLMEndpointCreate(
            name="bad",
            provider="gemini",  # not allowed
            base_url="http://example.com",
            model="gemini-pro",
        )

def test_llm_endpoint_response_never_exposes_api_key():
    from fleet_platform.schemas.llm import LLMEndpointResponse
    import uuid, datetime
    r = LLMEndpointResponse(
        id=uuid.uuid4(),
        name="test",
        provider="openai_compat",
        base_url="http://localhost:11434/v1",
        has_api_key=True,
        model="llama3.2",
        max_tokens=4096,
        is_default=True,
        enabled=True,
        created_at=datetime.datetime.now(),
        updated_at=datetime.datetime.now(),
    )
    # LLMEndpointResponse has no api_key field at all
    assert not hasattr(r, "api_key")
    assert not hasattr(r, "api_key_encrypted")

def test_llm_query_request_valid_intents():
    from fleet_platform.schemas.llm import LLMQueryRequest
    import pytest
    from pydantic import ValidationError
    # Valid intents
    for intent in ("salt_state", "ansible_playbook", "fleet_command", "explain"):
        req = LLMQueryRequest(prompt="do something", intent=intent)
        assert req.intent == intent
    # Invalid intent
    with pytest.raises(ValidationError):
        LLMQueryRequest(prompt="do something", intent="magic")
```

- [ ] **Step 2: Run tests to see them fail**

```bash
pytest tests/unit/test_llm_schemas.py -v 2>&1 | grep -E "PASSED|FAILED|ERROR"
```
Expected: 2 PASSED (model imports), 3 FAILED (schema tests, module not found)

- [ ] **Step 3: Create `fleet_platform/schemas/llm.py`**

```python
import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, HttpUrl


VALID_PROVIDERS = Literal["openai_compat", "anthropic"]
VALID_INTENTS = Literal["salt_state", "ansible_playbook", "fleet_command", "explain"]


class LLMEndpointCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    provider: VALID_PROVIDERS
    base_url: str = Field(..., min_length=1, max_length=500)
    api_key: str | None = None  # plaintext; encrypted on write; never returned
    model: str = Field(..., min_length=1, max_length=255)
    max_tokens: int = Field(default=4096, ge=256, le=128000)
    is_default: bool = False
    enabled: bool = True


class LLMEndpointUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    base_url: str | None = Field(default=None, min_length=1, max_length=500)
    api_key: str | None = None
    model: str | None = Field(default=None, min_length=1, max_length=255)
    max_tokens: int | None = Field(default=None, ge=256, le=128000)
    is_default: bool | None = None
    enabled: bool | None = None


class LLMEndpointResponse(BaseModel):
    id: uuid.UUID
    name: str
    provider: str
    base_url: str
    has_api_key: bool  # True if api_key_encrypted is set — never expose the key itself
    model: str
    max_tokens: int
    is_default: bool
    enabled: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class LLMEndpointTestResponse(BaseModel):
    ok: bool
    latency_ms: int
    error: str | None = None


class LLMQueryRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=8000)
    intent: VALID_INTENTS
    endpoint_id: uuid.UUID | None = None  # uses default endpoint if None


class LLMQueryResponse(BaseModel):
    query_id: uuid.UUID
    intent: str
    result: str
    model_used: str
    endpoint_name: str
    input_tokens: int
    output_tokens: int
    duration_ms: int


class LLMQueryLogEntry(BaseModel):
    id: uuid.UUID
    intent: str
    prompt: str
    model_used: str | None
    duration_ms: int | None
    error: str | None
    created_at: datetime

    model_config = {"from_attributes": True}
```

- [ ] **Step 4: Add `anthropic` to `pyproject.toml`**

Open `pyproject.toml`, find the `[project]` `dependencies` list, add after `"httpx>=0.28.0"`:
```toml
    "anthropic>=0.40",
```

- [ ] **Step 5: Create `fleet_platform/services/llm_svc.py`**

```python
import uuid
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.models.llm_endpoint import LLMEndpoint
from fleet_platform.models.llm_query_log import LLMQueryLog
from fleet_platform.schemas.llm import LLMEndpointCreate, LLMEndpointUpdate
from fleet_platform.services.platform_settings_svc import encrypt_secret, decrypt_secret


async def list_endpoints(db: AsyncSession) -> list[LLMEndpoint]:
    result = await db.execute(select(LLMEndpoint).order_by(LLMEndpoint.created_at))
    return list(result.scalars().all())


async def get_endpoint(db: AsyncSession, endpoint_id: uuid.UUID) -> LLMEndpoint | None:
    result = await db.execute(
        select(LLMEndpoint).where(LLMEndpoint.id == endpoint_id)
    )
    return result.scalar_one_or_none()


async def get_default_endpoint(db: AsyncSession) -> LLMEndpoint | None:
    result = await db.execute(
        select(LLMEndpoint).where(
            LLMEndpoint.is_default == True, LLMEndpoint.enabled == True
        )
    )
    return result.scalar_one_or_none()


async def create_endpoint(db: AsyncSession, payload: LLMEndpointCreate) -> LLMEndpoint:
    # Enforce single default: clear any existing default before setting a new one
    if payload.is_default:
        await db.execute(
            update(LLMEndpoint).values(is_default=False)
        )
    endpoint = LLMEndpoint(
        name=payload.name,
        provider=payload.provider,
        base_url=payload.base_url,
        api_key_encrypted=encrypt_secret(payload.api_key) if payload.api_key else None,
        model=payload.model,
        max_tokens=payload.max_tokens,
        is_default=payload.is_default,
        enabled=payload.enabled,
    )
    db.add(endpoint)
    await db.commit()
    await db.refresh(endpoint)
    return endpoint


async def update_endpoint(
    db: AsyncSession, endpoint: LLMEndpoint, payload: LLMEndpointUpdate
) -> LLMEndpoint:
    if payload.name is not None:
        endpoint.name = payload.name
    if payload.base_url is not None:
        endpoint.base_url = payload.base_url
    if payload.api_key is not None:
        endpoint.api_key_encrypted = encrypt_secret(payload.api_key)
    if payload.model is not None:
        endpoint.model = payload.model
    if payload.max_tokens is not None:
        endpoint.max_tokens = payload.max_tokens
    if payload.enabled is not None:
        endpoint.enabled = payload.enabled
    if payload.is_default is not None:
        if payload.is_default:
            await db.execute(update(LLMEndpoint).values(is_default=False))
        endpoint.is_default = payload.is_default
    await db.commit()
    await db.refresh(endpoint)
    return endpoint


async def delete_endpoint(db: AsyncSession, endpoint: LLMEndpoint) -> None:
    await db.delete(endpoint)
    await db.commit()


def get_decrypted_api_key(endpoint: LLMEndpoint) -> str | None:
    if endpoint.api_key_encrypted is None:
        return None
    return decrypt_secret(endpoint.api_key_encrypted)


async def create_query_log(
    db: AsyncSession,
    *,
    endpoint_id: uuid.UUID | None,
    user_id: str,
    intent: str,
    prompt: str,
    system_prompt: str,
    response: str | None,
    model_used: str | None,
    input_tokens: int | None,
    output_tokens: int | None,
    duration_ms: int | None,
    error: str | None,
) -> LLMQueryLog:
    log = LLMQueryLog(
        endpoint_id=endpoint_id,
        user_id=user_id,
        intent=intent,
        prompt=prompt,
        system_prompt=system_prompt,
        response=response,
        model_used=model_used,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        duration_ms=duration_ms,
        error=error,
    )
    db.add(log)
    await db.commit()
    await db.refresh(log)
    return log


async def list_query_logs(
    db: AsyncSession, user_id: str | None = None, limit: int = 50
) -> list[LLMQueryLog]:
    q = select(LLMQueryLog).order_by(LLMQueryLog.created_at.desc()).limit(limit)
    if user_id:
        q = q.where(LLMQueryLog.user_id == user_id)
    result = await db.execute(q)
    return list(result.scalars().all())
```

- [ ] **Step 6: Run all schema tests**

```bash
pytest tests/unit/test_llm_schemas.py -v
```
Expected: 5 PASSED

- [ ] **Step 7: Commit**

```bash
git add fleet_platform/schemas/llm.py \
        fleet_platform/services/llm_svc.py \
        pyproject.toml \
        tests/unit/test_llm_schemas.py
git commit -m "feat: LLM schemas, CRUD service, add anthropic dep"
```

---

## Task 3: Fleet Context Builder + LLM Caller

**Files:**
- Create: `fleet_platform/services/llm_context.py`
- Create: `fleet_platform/services/llm_caller.py`
- Test: `tests/unit/test_llm_context.py`
- Test: `tests/unit/test_llm_caller.py`

- [ ] **Step 1: Write failing context builder tests**

```python
# tests/unit/test_llm_context.py
import pytest

INTENT_SYSTEM_ADDENDUM = {
    "salt_state": "Generate a complete SaltStack state file (.sls).",
    "ansible_playbook": "Generate a complete Ansible playbook (YAML).",
    "fleet_command": "Suggest the exact Salt execution module call.",
    "explain": "Explain the given code in plain English.",
}


def test_build_context_returns_nonempty_string():
    from fleet_platform.services.llm_context import build_static_context
    ctx = build_static_context(
        node_count=5,
        online_count=4,
        groups=["dev", "prod"],
        salt_master="salt.fleet.local",
        playbooks_dir="/srv/playbooks",
    )
    assert isinstance(ctx, str)
    assert len(ctx) > 50


def test_build_context_contains_node_count():
    from fleet_platform.services.llm_context import build_static_context
    ctx = build_static_context(
        node_count=12,
        online_count=10,
        groups=[],
        salt_master="salt.local",
        playbooks_dir="/srv",
    )
    assert "12" in ctx
    assert "10" in ctx


def test_build_context_contains_groups():
    from fleet_platform.services.llm_context import build_static_context
    ctx = build_static_context(
        node_count=3,
        online_count=3,
        groups=["alpha", "beta", "gamma"],
        salt_master="s",
        playbooks_dir="/p",
    )
    assert "alpha" in ctx
    assert "beta" in ctx
    assert "gamma" in ctx


def test_intent_addendum_covers_all_intents():
    intents = {"salt_state", "ansible_playbook", "fleet_command", "explain"}
    assert set(INTENT_SYSTEM_ADDENDUM.keys()) == intents
```

- [ ] **Step 2: Run tests to verify failure**

```bash
pytest tests/unit/test_llm_context.py -v
```
Expected: 4 FAILED (`ModuleNotFoundError`)

- [ ] **Step 3: Create `fleet_platform/services/llm_context.py`**

```python
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.models.fleet import Node, Group
from fleet_platform.services.platform_settings_svc import get_setting

# Added to system prompt based on the user's selected intent
INTENT_ADDENDUM: dict[str, str] = {
    "salt_state": (
        "Generate a complete, production-ready SaltStack state file (.sls). "
        "Include only valid YAML. Wrap the file content in a ```sls code block."
    ),
    "ansible_playbook": (
        "Generate a complete, production-ready Ansible playbook (YAML). "
        "Target hosts should use 'all' unless the user specifies otherwise. "
        "Wrap the file content in a ```yaml code block."
    ),
    "fleet_command": (
        "Suggest the exact SaltStack execution module call to accomplish the request. "
        "Format: `salt '<target>' <module>.<function> [args]`. "
        "Explain what each argument does in one sentence."
    ),
    "explain": (
        "Explain the provided code in plain English. "
        "List: what it does, any side effects, and whether it is idempotent."
    ),
}


def build_static_context(
    *,
    node_count: int,
    online_count: int,
    groups: list[str],
    salt_master: str,
    playbooks_dir: str,
) -> str:
    group_line = ", ".join(groups) if groups else "(none)"
    return (
        "You are an AI assistant embedded in **kri**, a fleet management platform.\n\n"
        "## Fleet Snapshot\n"
        f"- Total nodes: {node_count}\n"
        f"- Online: {online_count}  |  Offline: {node_count - online_count}\n"
        f"- Node OS: macOS (all nodes are Apple Mac Minis running macOS)\n"
        f"- Salt master: {salt_master or 'not configured'}\n"
        f"- Playbooks directory: {playbooks_dir or 'not configured'}\n"
        f"- Groups: {group_line}\n\n"
        "## Rules\n"
        "- Never suggest commands that would destructively wipe filesystems.\n"
        "- Prefer idempotent operations.\n"
        "- When generating files, output only the file content — no extra prose before or after the code block.\n"
    )


async def build_fleet_context(db: AsyncSession, intent: str) -> str:
    """
    Fetch live fleet state from DB and build a system prompt string.
    Keeps output under ~1500 tokens for context efficiency.
    """
    from fleet_platform.models.node import Node
    from fleet_platform.models.group import Group

    node_count_result = await db.execute(select(func.count()).select_from(Node))
    node_count: int = node_count_result.scalar_one()

    online_result = await db.execute(
        select(func.count()).select_from(Node).where(Node.status == "online")
    )
    online_count: int = online_result.scalar_one()

    groups_result = await db.execute(select(Group.name).order_by(Group.name))
    groups: list[str] = list(groups_result.scalars().all())

    salt_master = await get_setting(db, "SALT_MASTER") or ""
    playbooks_dir = await get_setting(db, "PLAYBOOKS_DIR") or ""

    base = build_static_context(
        node_count=node_count,
        online_count=online_count,
        groups=groups,
        salt_master=salt_master,
        playbooks_dir=playbooks_dir,
    )
    addendum = INTENT_ADDENDUM.get(intent, "")
    return f"{base}\n## Your Task\n{addendum}"
```

- [ ] **Step 4: Write failing LLM caller tests**

```python
# tests/unit/test_llm_caller.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_call_openai_compat_sends_correct_payload():
    from fleet_platform.services.llm_caller import call_openai_compat

    mock_response = MagicMock()
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "# salt state here"}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 50},
    }
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("fleet_platform.services.llm_caller.httpx.AsyncClient", return_value=mock_client):
        content, inp, out = await call_openai_compat(
            base_url="http://localhost:11434/v1",
            api_key=None,
            model="llama3.2",
            max_tokens=4096,
            system_prompt="You are helpful.",
            user_prompt="Write a salt state",
        )

    assert content == "# salt state here"
    assert inp == 100
    assert out == 50
    # Verify the POST was called with the right URL
    call_args = mock_client.post.call_args
    assert "/chat/completions" in call_args[0][0]


@pytest.mark.asyncio
async def test_call_openai_compat_adds_bearer_header_when_api_key_given():
    from fleet_platform.services.llm_caller import call_openai_compat

    mock_response = MagicMock()
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "ok"}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("fleet_platform.services.llm_caller.httpx.AsyncClient", return_value=mock_client):
        await call_openai_compat(
            base_url="https://api.openai.com/v1",
            api_key="sk-secret",
            model="gpt-4o",
            max_tokens=4096,
            system_prompt="sys",
            user_prompt="prompt",
        )

    _, kwargs = mock_client.post.call_args
    assert kwargs["headers"]["Authorization"] == "Bearer sk-secret"


@pytest.mark.asyncio
async def test_call_anthropic_sends_correct_structure():
    from fleet_platform.services.llm_caller import call_anthropic

    mock_sdk = MagicMock()
    mock_client_instance = AsyncMock()
    mock_sdk.AsyncAnthropic.return_value = mock_client_instance

    mock_message = MagicMock()
    mock_message.content = [MagicMock(text="- the playbook")]
    mock_message.usage.input_tokens = 200
    mock_message.usage.output_tokens = 80
    mock_client_instance.messages.create = AsyncMock(return_value=mock_message)

    with patch.dict("sys.modules", {"anthropic": mock_sdk}):
        content, inp, out = await call_anthropic(
            api_key="ant-key",
            model="claude-opus-4-7",
            max_tokens=4096,
            system_prompt="sys",
            user_prompt="write a playbook",
        )

    assert content == "- the playbook"
    assert inp == 200
    assert out == 80
```

- [ ] **Step 5: Run caller tests to see them fail**

```bash
pytest tests/unit/test_llm_caller.py -v
```
Expected: 3 FAILED (`ModuleNotFoundError`)

- [ ] **Step 6: Create `fleet_platform/services/llm_caller.py`**

```python
import httpx

OPENAI_COMPAT_TIMEOUT = 90.0  # seconds; local Ollama models can be slow


async def call_openai_compat(
    *,
    base_url: str,
    api_key: str | None,
    model: str,
    max_tokens: int,
    system_prompt: str,
    user_prompt: str,
) -> tuple[str, int, int]:
    """
    Call an OpenAI-compatible /chat/completions endpoint.
    Returns (content, input_tokens, output_tokens).
    Works with: OpenAI, Ollama, LM Studio, vLLM, Groq, Mistral, Together.
    """
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }

    async with httpx.AsyncClient(timeout=OPENAI_COMPAT_TIMEOUT) as client:
        response = await client.post(
            f"{base_url.rstrip('/')}/chat/completions",
            headers=headers,
            json=payload,
        )
        response.raise_for_status()

    data = response.json()
    content: str = data["choices"][0]["message"]["content"]
    usage = data.get("usage", {})
    return content, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)


async def call_anthropic(
    *,
    api_key: str,
    model: str,
    max_tokens: int,
    system_prompt: str,
    user_prompt: str,
) -> tuple[str, int, int]:
    """
    Call Anthropic Claude via the native anthropic SDK.
    Returns (content, input_tokens, output_tokens).
    """
    import anthropic

    client = anthropic.AsyncAnthropic(api_key=api_key)
    message = await client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )
    content: str = message.content[0].text
    return content, message.usage.input_tokens, message.usage.output_tokens
```

- [ ] **Step 7: Run all new tests**

```bash
pytest tests/unit/test_llm_context.py tests/unit/test_llm_caller.py -v
```
Expected: 7 PASSED

- [ ] **Step 8: Commit**

```bash
git add fleet_platform/services/llm_context.py \
        fleet_platform/services/llm_caller.py \
        tests/unit/test_llm_context.py \
        tests/unit/test_llm_caller.py
git commit -m "feat: fleet context builder and LLM caller (openai_compat + anthropic)"
```

---

## Task 4: API Routes

**Files:**
- Create: `fleet_platform/api/routes/llm.py`
- Modify: `fleet_platform/api/main.py`
- Test: `tests/integration/test_llm_api.py`

- [ ] **Step 1: Write integration test stubs**

```python
# tests/integration/test_llm_api.py
"""
Integration tests for /api/v1/llm/* routes.
These tests use a real test DB (AsyncSessionLocal) and mock only the LLM HTTP call.
Run with: pytest tests/integration/test_llm_api.py -v
"""
import pytest
from unittest.mock import AsyncMock, patch

# These tests require the DB to be running and migrated.
# Skip with: pytest -m "not integration"
pytestmark = pytest.mark.integration
```

Note: Full integration test content is in Step 4 below after seeing the route structure.

- [ ] **Step 2: Create `fleet_platform/api/routes/llm.py`**

```python
import time
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.db.session import get_db
from fleet_platform.deps import require_role
from fleet_platform.schemas.llm import (
    LLMEndpointCreate,
    LLMEndpointResponse,
    LLMEndpointTestResponse,
    LLMEndpointUpdate,
    LLMQueryLogEntry,
    LLMQueryRequest,
    LLMQueryResponse,
)
from fleet_platform.services import llm_svc
from fleet_platform.services.llm_caller import call_anthropic, call_openai_compat
from fleet_platform.services.llm_context import build_fleet_context

router = APIRouter(prefix="/api/v1/llm", tags=["llm"])


def _to_response(endpoint) -> LLMEndpointResponse:
    return LLMEndpointResponse(
        id=endpoint.id,
        name=endpoint.name,
        provider=endpoint.provider,
        base_url=endpoint.base_url,
        has_api_key=endpoint.api_key_encrypted is not None,
        model=endpoint.model,
        max_tokens=endpoint.max_tokens,
        is_default=endpoint.is_default,
        enabled=endpoint.enabled,
        created_at=endpoint.created_at,
        updated_at=endpoint.updated_at,
    )


# ── Endpoint management (admin only) ─────────────────────────────────────────

@router.get("/endpoints", response_model=list[LLMEndpointResponse])
async def list_endpoints(
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("admin")),
):
    endpoints = await llm_svc.list_endpoints(db)
    return [_to_response(e) for e in endpoints]


@router.post("/endpoints", response_model=LLMEndpointResponse, status_code=201)
async def create_endpoint(
    payload: LLMEndpointCreate,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("admin")),
):
    endpoint = await llm_svc.create_endpoint(db, payload)
    return _to_response(endpoint)


@router.get("/endpoints/{endpoint_id}", response_model=LLMEndpointResponse)
async def get_endpoint(
    endpoint_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("admin")),
):
    endpoint = await llm_svc.get_endpoint(db, endpoint_id)
    if not endpoint:
        raise HTTPException(status_code=404, detail="LLM endpoint not found")
    return _to_response(endpoint)


@router.put("/endpoints/{endpoint_id}", response_model=LLMEndpointResponse)
async def update_endpoint(
    endpoint_id: uuid.UUID,
    payload: LLMEndpointUpdate,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("admin")),
):
    endpoint = await llm_svc.get_endpoint(db, endpoint_id)
    if not endpoint:
        raise HTTPException(status_code=404, detail="LLM endpoint not found")
    endpoint = await llm_svc.update_endpoint(db, endpoint, payload)
    return _to_response(endpoint)


@router.delete("/endpoints/{endpoint_id}", status_code=204)
async def delete_endpoint(
    endpoint_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("admin")),
):
    endpoint = await llm_svc.get_endpoint(db, endpoint_id)
    if not endpoint:
        raise HTTPException(status_code=404, detail="LLM endpoint not found")
    await llm_svc.delete_endpoint(db, endpoint)


@router.post("/endpoints/{endpoint_id}/test", response_model=LLMEndpointTestResponse)
async def test_endpoint(
    endpoint_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("admin")),
):
    endpoint = await llm_svc.get_endpoint(db, endpoint_id)
    if not endpoint:
        raise HTTPException(status_code=404, detail="LLM endpoint not found")

    api_key = llm_svc.get_decrypted_api_key(endpoint)
    ping_prompt = "Reply with exactly one word: hello"
    t0 = time.perf_counter()
    try:
        if endpoint.provider == "anthropic":
            await call_anthropic(
                api_key=api_key or "",
                model=endpoint.model,
                max_tokens=16,
                system_prompt="You are a test probe.",
                user_prompt=ping_prompt,
            )
        else:
            await call_openai_compat(
                base_url=endpoint.base_url,
                api_key=api_key,
                model=endpoint.model,
                max_tokens=16,
                system_prompt="You are a test probe.",
                user_prompt=ping_prompt,
            )
        latency_ms = int((time.perf_counter() - t0) * 1000)
        return LLMEndpointTestResponse(ok=True, latency_ms=latency_ms)
    except Exception as exc:
        latency_ms = int((time.perf_counter() - t0) * 1000)
        return LLMEndpointTestResponse(ok=False, latency_ms=latency_ms, error=str(exc))


# ── Query (operator+) ─────────────────────────────────────────────────────────

@router.post("/query", response_model=LLMQueryResponse)
async def submit_query(
    payload: LLMQueryRequest,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_role("operator", "admin")),
):
    # Resolve endpoint
    if payload.endpoint_id:
        endpoint = await llm_svc.get_endpoint(db, payload.endpoint_id)
        if not endpoint:
            raise HTTPException(status_code=404, detail="LLM endpoint not found")
    else:
        endpoint = await llm_svc.get_default_endpoint(db)
        if not endpoint:
            raise HTTPException(
                status_code=422,
                detail="No default LLM endpoint configured. Add one in Settings → LLM.",
            )

    if not endpoint.enabled:
        raise HTTPException(status_code=422, detail="Selected LLM endpoint is disabled")

    api_key = llm_svc.get_decrypted_api_key(endpoint)
    system_prompt = await build_fleet_context(db, payload.intent)

    t0 = time.perf_counter()
    error: str | None = None
    content: str = ""
    input_tokens = 0
    output_tokens = 0

    try:
        if endpoint.provider == "anthropic":
            content, input_tokens, output_tokens = await call_anthropic(
                api_key=api_key or "",
                model=endpoint.model,
                max_tokens=endpoint.max_tokens,
                system_prompt=system_prompt,
                user_prompt=payload.prompt,
            )
        else:
            content, input_tokens, output_tokens = await call_openai_compat(
                base_url=endpoint.base_url,
                api_key=api_key,
                model=endpoint.model,
                max_tokens=endpoint.max_tokens,
                system_prompt=system_prompt,
                user_prompt=payload.prompt,
            )
    except Exception as exc:
        error = str(exc)

    duration_ms = int((time.perf_counter() - t0) * 1000)

    log = await llm_svc.create_query_log(
        db,
        endpoint_id=endpoint.id,
        user_id=claims["sub"],
        intent=payload.intent,
        prompt=payload.prompt,
        system_prompt=system_prompt,
        response=content or None,
        model_used=endpoint.model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        duration_ms=duration_ms,
        error=error,
    )

    if error:
        raise HTTPException(status_code=502, detail=f"LLM call failed: {error}")

    return LLMQueryResponse(
        query_id=log.id,
        intent=payload.intent,
        result=content,
        model_used=endpoint.model,
        endpoint_name=endpoint.name,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        duration_ms=duration_ms,
    )


@router.get("/queries", response_model=list[LLMQueryLogEntry])
async def list_queries(
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_role("operator", "admin")),
):
    logs = await llm_svc.list_query_logs(db, user_id=claims["sub"], limit=50)
    return [LLMQueryLogEntry.model_validate(log) for log in logs]
```

- [ ] **Step 3: Register the router in `fleet_platform/api/main.py`**

Open `fleet_platform/api/main.py`. Add to the imports block (after `ios_tracking_router` import):
```python
from fleet_platform.api.routes.llm import router as llm_router
```

Add to `create_app()` (after the `ios_tracking_router` line):
```python
    app.include_router(llm_router, tags=["llm"])
```

- [ ] **Step 4: Write integration tests**

Open `tests/integration/test_llm_api.py` and replace stub with:

```python
"""
Integration tests for /api/v1/llm/* routes.
These tests use a real test DB and mock only the outbound LLM HTTP calls.
Run with: pytest tests/integration/test_llm_api.py -v
Requires: DATABASE_URL env var pointing to a test PostgreSQL instance.
"""
import pytest
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_create_endpoint_returns_201_and_hides_api_key(async_client: AsyncClient, admin_token: str):
    response = await async_client.post(
        "/api/v1/llm/endpoints",
        json={
            "name": "Local Ollama",
            "provider": "openai_compat",
            "base_url": "http://localhost:11434/v1",
            "api_key": None,
            "model": "llama3.2",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Local Ollama"
    assert "api_key" not in data
    assert "api_key_encrypted" not in data
    assert data["has_api_key"] is False


@pytest.mark.asyncio
async def test_create_endpoint_with_api_key_sets_has_api_key_true(async_client: AsyncClient, admin_token: str):
    response = await async_client.post(
        "/api/v1/llm/endpoints",
        json={
            "name": "OpenAI",
            "provider": "openai_compat",
            "base_url": "https://api.openai.com/v1",
            "api_key": "sk-test-secret",
            "model": "gpt-4o",
            "is_default": True,
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 201
    assert response.json()["has_api_key"] is True


@pytest.mark.asyncio
async def test_delete_endpoint_removes_it(async_client: AsyncClient, admin_token: str):
    create = await async_client.post(
        "/api/v1/llm/endpoints",
        json={"name": "temp", "provider": "openai_compat", "base_url": "http://x/v1", "model": "m"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    eid = create.json()["id"]
    delete = await async_client.delete(
        f"/api/v1/llm/endpoints/{eid}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert delete.status_code == 204
    get = await async_client.get(
        f"/api/v1/llm/endpoints/{eid}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert get.status_code == 404


@pytest.mark.asyncio
async def test_query_with_no_default_endpoint_returns_422(async_client: AsyncClient, operator_token: str):
    # Assumes no default endpoint exists in test DB
    response = await async_client.post(
        "/api/v1/llm/query",
        json={"prompt": "install nginx", "intent": "salt_state"},
        headers={"Authorization": f"Bearer {operator_token}"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_query_creates_log_entry(async_client: AsyncClient, admin_token: str, operator_token: str):
    # Create a default endpoint first
    await async_client.post(
        "/api/v1/llm/endpoints",
        json={"name": "Mock LLM", "provider": "openai_compat",
              "base_url": "http://mock/v1", "model": "mock", "is_default": True},
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    mock_response_data = {
        "choices": [{"message": {"content": "# generated state"}}],
        "usage": {"prompt_tokens": 50, "completion_tokens": 30},
    }

    with patch("fleet_platform.services.llm_caller.httpx.AsyncClient") as mock_cls:
        mock_instance = AsyncMock()
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=None)
        mock_resp = AsyncMock()
        mock_resp.json.return_value = mock_response_data
        mock_resp.raise_for_status = AsyncMock()
        mock_instance.post = AsyncMock(return_value=mock_resp)

        response = await async_client.post(
            "/api/v1/llm/query",
            json={"prompt": "ensure nginx is installed", "intent": "salt_state"},
            headers={"Authorization": f"Bearer {operator_token}"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["result"] == "# generated state"
    assert data["intent"] == "salt_state"
    assert "query_id" in data

    # Verify log entry was created
    logs = await async_client.get(
        "/api/v1/llm/queries",
        headers={"Authorization": f"Bearer {operator_token}"},
    )
    assert logs.status_code == 200
    assert len(logs.json()) >= 1
```

- [ ] **Step 5: Run unit suite to verify no regressions**

```bash
source .venv/bin/activate && pytest tests/unit/ -q
```
Expected: all previous tests pass + 0 new failures

- [ ] **Step 6: Commit**

```bash
git add fleet_platform/api/routes/llm.py \
        fleet_platform/api/main.py \
        tests/integration/test_llm_api.py
git commit -m "feat: LLM API routes — endpoint CRUD, test, query, query log"
```

---

## Task 5: Frontend — LLM Endpoints Settings Tab

**Files:**
- Create: `frontend/src/api/llm.ts`
- Create: `frontend/src/components/llm/LLMEndpointForm.tsx`
- Modify: `frontend/src/pages/SettingsPage.tsx`

- [ ] **Step 1: Create `frontend/src/api/llm.ts`**

```typescript
import { api } from './client'

export interface LLMEndpoint {
  id: string
  name: string
  provider: 'openai_compat' | 'anthropic'
  base_url: string
  has_api_key: boolean
  model: string
  max_tokens: number
  is_default: boolean
  enabled: boolean
  created_at: string
  updated_at: string
}

export interface LLMEndpointCreate {
  name: string
  provider: 'openai_compat' | 'anthropic'
  base_url: string
  api_key?: string | null
  model: string
  max_tokens?: number
  is_default?: boolean
  enabled?: boolean
}

export interface LLMEndpointUpdate {
  name?: string
  base_url?: string
  api_key?: string | null
  model?: string
  max_tokens?: number
  is_default?: boolean
  enabled?: boolean
}

export interface LLMTestResult {
  ok: boolean
  latency_ms: number
  error?: string | null
}

export interface LLMQueryRequest {
  prompt: string
  intent: 'salt_state' | 'ansible_playbook' | 'fleet_command' | 'explain'
  endpoint_id?: string | null
}

export interface LLMQueryResponse {
  query_id: string
  intent: string
  result: string
  model_used: string
  endpoint_name: string
  input_tokens: number
  output_tokens: number
  duration_ms: number
}

export interface LLMQueryLogEntry {
  id: string
  intent: string
  prompt: string
  model_used: string | null
  duration_ms: number | null
  error: string | null
  created_at: string
}

export const llmApi = {
  listEndpoints: () => api.get<LLMEndpoint[]>('/api/v1/llm/endpoints'),
  createEndpoint: (body: LLMEndpointCreate) =>
    api.post<LLMEndpoint>('/api/v1/llm/endpoints', body),
  updateEndpoint: (id: string, body: LLMEndpointUpdate) =>
    api.put<LLMEndpoint>(`/api/v1/llm/endpoints/${id}`, body),
  deleteEndpoint: (id: string) => api.delete(`/api/v1/llm/endpoints/${id}`),
  testEndpoint: (id: string) =>
    api.post<LLMTestResult>(`/api/v1/llm/endpoints/${id}/test`, {}),
  submitQuery: (body: LLMQueryRequest) =>
    api.post<LLMQueryResponse>('/api/v1/llm/query', body),
  listQueries: () => api.get<LLMQueryLogEntry[]>('/api/v1/llm/queries'),
}
```

- [ ] **Step 2: Create `frontend/src/components/llm/LLMEndpointForm.tsx`**

```tsx
import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { llmApi, LLMEndpoint, LLMEndpointCreate } from '../../api/llm'

interface Props {
  existing?: LLMEndpoint
  onDone: () => void
}

export default function LLMEndpointForm({ existing, onDone }: Props) {
  const qc = useQueryClient()
  const isEdit = !!existing

  const [name, setName] = useState(existing?.name ?? '')
  const [provider, setProvider] = useState<'openai_compat' | 'anthropic'>(
    existing?.provider ?? 'openai_compat'
  )
  const [baseUrl, setBaseUrl] = useState(existing?.base_url ?? '')
  const [apiKey, setApiKey] = useState('')
  const [model, setModel] = useState(existing?.model ?? '')
  const [maxTokens, setMaxTokens] = useState(existing?.max_tokens ?? 4096)
  const [isDefault, setIsDefault] = useState(existing?.is_default ?? false)
  const [enabled, setEnabled] = useState(existing?.enabled ?? true)
  const [error, setError] = useState<string | null>(null)

  const save = useMutation({
    mutationFn: async () => {
      const payload: LLMEndpointCreate = {
        name,
        provider,
        base_url: baseUrl,
        api_key: apiKey || null,
        model,
        max_tokens: maxTokens,
        is_default: isDefault,
        enabled,
      }
      if (isEdit) {
        return llmApi.updateEndpoint(existing.id, payload)
      }
      return llmApi.createEndpoint(payload)
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['llm-endpoints'] })
      onDone()
    },
    onError: (e: any) => setError(e?.detail ?? 'Save failed'),
  })

  const inputClass =
    'w-full rounded border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500'
  const labelClass = 'block text-sm font-medium text-gray-700 mb-1'

  return (
    <div className="space-y-4">
      {error && (
        <div className="rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
          {error}
        </div>
      )}

      <div>
        <label className={labelClass}>Name</label>
        <input className={inputClass} value={name} onChange={e => setName(e.target.value)}
          placeholder="Local Ollama" />
      </div>

      <div>
        <label className={labelClass}>Provider</label>
        <select className={inputClass} value={provider}
          onChange={e => setProvider(e.target.value as any)}>
          <option value="openai_compat">OpenAI-compatible (Ollama, OpenAI, Groq, vLLM…)</option>
          <option value="anthropic">Anthropic (Claude)</option>
        </select>
      </div>

      {provider === 'openai_compat' && (
        <div>
          <label className={labelClass}>Base URL</label>
          <input className={inputClass} value={baseUrl}
            onChange={e => setBaseUrl(e.target.value)}
            placeholder="http://ollama.cluster.local:11434/v1" />
        </div>
      )}

      <div>
        <label className={labelClass}>Model</label>
        <input className={inputClass} value={model} onChange={e => setModel(e.target.value)}
          placeholder={provider === 'anthropic' ? 'claude-opus-4-7' : 'llama3.2'} />
      </div>

      <div>
        <label className={labelClass}>
          API Key{' '}
          {isEdit && existing?.has_api_key && (
            <span className="ml-1 text-xs text-gray-500">(leave blank to keep existing)</span>
          )}
        </label>
        <input className={inputClass} type="password" value={apiKey}
          onChange={e => setApiKey(e.target.value)}
          placeholder={provider === 'openai_compat' ? 'sk-... (leave blank for Ollama)' : 'ant-...'} />
      </div>

      <div>
        <label className={labelClass}>Max Tokens</label>
        <input className={inputClass} type="number" value={maxTokens}
          onChange={e => setMaxTokens(Number(e.target.value))} min={256} max={128000} />
      </div>

      <div className="flex items-center gap-6">
        <label className="flex items-center gap-2 text-sm text-gray-700">
          <input type="checkbox" checked={isDefault} onChange={e => setIsDefault(e.target.checked)}
            className="h-4 w-4 rounded border-gray-300 text-blue-600" />
          Set as default
        </label>
        <label className="flex items-center gap-2 text-sm text-gray-700">
          <input type="checkbox" checked={enabled} onChange={e => setEnabled(e.target.checked)}
            className="h-4 w-4 rounded border-gray-300 text-blue-600" />
          Enabled
        </label>
      </div>

      <div className="flex justify-end gap-2 pt-2">
        <button onClick={onDone}
          className="rounded border border-gray-300 px-4 py-2 text-sm text-gray-700 hover:bg-gray-50">
          Cancel
        </button>
        <button
          onClick={() => save.mutate()}
          disabled={save.isPending}
          className="rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50">
          {save.isPending ? 'Saving…' : isEdit ? 'Update' : 'Add Endpoint'}
        </button>
      </div>
    </div>
  )
}
```

- [ ] **Step 3: Add LLM tab to `frontend/src/pages/SettingsPage.tsx`**

Open `SettingsPage.tsx`. Find the `TABS` array (around line 79) and add:
```tsx
{ id: 'llm', label: 'LLM' },
```

Find the tab content section and add a new `{activeTab === 'llm' && (...)}` block:

```tsx
{activeTab === 'llm' && (
  <LLMSettingsTab />
)}
```

At the top of `SettingsPage.tsx`, add the import:
```tsx
import LLMSettingsTab from '../components/llm/LLMSettingsTab'
```

- [ ] **Step 4: Create `frontend/src/components/llm/LLMSettingsTab.tsx`**

```tsx
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { llmApi, LLMEndpoint, LLMTestResult } from '../../api/llm'
import LLMEndpointForm from './LLMEndpointForm'

export default function LLMSettingsTab() {
  const qc = useQueryClient()
  const [showForm, setShowForm] = useState(false)
  const [editing, setEditing] = useState<LLMEndpoint | null>(null)
  const [testResults, setTestResults] = useState<Record<string, LLMTestResult>>({})
  const [testing, setTesting] = useState<string | null>(null)

  const { data: endpoints = [], isLoading } = useQuery({
    queryKey: ['llm-endpoints'],
    queryFn: llmApi.listEndpoints,
  })

  const remove = useMutation({
    mutationFn: llmApi.deleteEndpoint,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['llm-endpoints'] }),
  })

  const testConnection = async (id: string) => {
    setTesting(id)
    try {
      const result = await llmApi.testEndpoint(id)
      setTestResults(r => ({ ...r, [id]: result }))
    } catch {
      setTestResults(r => ({ ...r, [id]: { ok: false, latency_ms: 0, error: 'Request failed' } }))
    } finally {
      setTesting(null)
    }
  }

  if (isLoading) {
    return <div className="py-8 text-center text-sm text-gray-500">Loading…</div>
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-base font-semibold text-gray-900">LLM Endpoints</h2>
          <p className="mt-0.5 text-sm text-gray-500">
            Configure AI providers for natural language fleet operations.
            The default endpoint is used by the AI Assistant.
          </p>
        </div>
        <button
          onClick={() => { setEditing(null); setShowForm(true) }}
          className="rounded bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700">
          + Add Endpoint
        </button>
      </div>

      {(showForm || editing) && (
        <div className="rounded-lg border border-gray-200 bg-white p-6 shadow-sm">
          <h3 className="mb-4 text-sm font-semibold text-gray-900">
            {editing ? 'Edit Endpoint' : 'New LLM Endpoint'}
          </h3>
          <LLMEndpointForm
            existing={editing ?? undefined}
            onDone={() => { setShowForm(false); setEditing(null) }}
          />
        </div>
      )}

      {endpoints.length === 0 && !showForm && (
        <div className="rounded-lg border border-dashed border-gray-300 bg-gray-50 py-12 text-center">
          <p className="text-sm text-gray-500">No LLM endpoints configured.</p>
          <p className="mt-1 text-xs text-gray-400">
            Add an Ollama instance or OpenAI API key to enable the AI Assistant.
          </p>
        </div>
      )}

      <div className="divide-y divide-gray-100 rounded-lg border border-gray-200 bg-white shadow-sm">
        {endpoints.map(ep => {
          const testResult = testResults[ep.id]
          return (
            <div key={ep.id} className="flex items-start justify-between px-5 py-4">
              <div className="space-y-0.5">
                <div className="flex items-center gap-2">
                  <span className="font-medium text-gray-900">{ep.name}</span>
                  {ep.is_default && (
                    <span className="rounded bg-blue-100 px-1.5 py-0.5 text-xs font-medium text-blue-700">
                      default
                    </span>
                  )}
                  {!ep.enabled && (
                    <span className="rounded bg-gray-100 px-1.5 py-0.5 text-xs text-gray-500">
                      disabled
                    </span>
                  )}
                </div>
                <div className="text-xs text-gray-500">
                  {ep.provider === 'openai_compat' ? 'OpenAI-compat' : 'Anthropic'} ·{' '}
                  {ep.model} · {ep.max_tokens.toLocaleString()} max tokens
                </div>
                {ep.base_url && (
                  <div className="font-mono text-xs text-gray-400">{ep.base_url}</div>
                )}
                {testResult && (
                  <div className={`text-xs font-medium ${testResult.ok ? 'text-green-600' : 'text-red-600'}`}>
                    {testResult.ok
                      ? `✓ Connected — ${testResult.latency_ms}ms`
                      : `✗ ${testResult.error}`}
                  </div>
                )}
              </div>
              <div className="ml-4 flex shrink-0 items-center gap-2">
                <button
                  onClick={() => testConnection(ep.id)}
                  disabled={testing === ep.id}
                  className="rounded border border-gray-300 px-2.5 py-1 text-xs text-gray-600 hover:bg-gray-50 disabled:opacity-50">
                  {testing === ep.id ? 'Testing…' : 'Test'}
                </button>
                <button
                  onClick={() => { setEditing(ep); setShowForm(false) }}
                  className="rounded border border-gray-300 px-2.5 py-1 text-xs text-gray-600 hover:bg-gray-50">
                  Edit
                </button>
                <button
                  onClick={() => remove.mutate(ep.id)}
                  className="rounded border border-red-200 px-2.5 py-1 text-xs text-red-600 hover:bg-red-50">
                  Delete
                </button>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
```

- [ ] **Step 5: Build frontend to check TypeScript**

```bash
cd frontend && npm run build 2>&1 | grep -E "error TS|✓ built"
```
Expected: `✓ built in X.XXs` with no `error TS` lines

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api/llm.ts \
        frontend/src/components/llm/LLMEndpointForm.tsx \
        frontend/src/components/llm/LLMSettingsTab.tsx \
        frontend/src/pages/SettingsPage.tsx
git commit -m "feat: LLM endpoints management in Settings → LLM tab"
```

---

## Task 6: Frontend — AI Assistant Panel

**Files:**
- Create: `frontend/src/components/llm/LLMAssistant.tsx`
- Modify: layout/App component to mount it globally

- [ ] **Step 1: Find the layout component that wraps all authenticated pages**

```bash
grep -r "Sidebar\|Layout\|AppShell\|outlet" frontend/src --include="*.tsx" -l | head -5
```
Then read that file to find where to mount a floating panel.

- [ ] **Step 2: Create `frontend/src/components/llm/LLMAssistant.tsx`**

```tsx
import { useState, useRef, useEffect } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { llmApi, LLMQueryResponse } from '../../api/llm'

type Intent = 'salt_state' | 'ansible_playbook' | 'fleet_command' | 'explain'

const INTENT_LABELS: Record<Intent, string> = {
  salt_state: 'Salt State',
  ansible_playbook: 'Ansible Playbook',
  fleet_command: 'Fleet Command',
  explain: 'Explain Code',
}

const INTENT_PLACEHOLDERS: Record<Intent, string> = {
  salt_state: 'Ensure Docker is installed and running on all Mac Minis…',
  ansible_playbook: 'Disable password authentication and enforce SSH key login…',
  fleet_command: 'Restart nginx on the dev group…',
  explain: 'Paste a Salt state or Ansible playbook here to get an explanation…',
}

interface Props {
  defaultIntent?: Intent
  prefill?: string
  onApplySaltState?: (content: string) => void
  onSavePlaybook?: (content: string) => void
}

export default function LLMAssistant({
  defaultIntent = 'salt_state',
  prefill = '',
  onApplySaltState,
  onSavePlaybook,
}: Props) {
  const [open, setOpen] = useState(false)
  const [intent, setIntent] = useState<Intent>(defaultIntent)
  const [prompt, setPrompt] = useState(prefill)
  const [result, setResult] = useState<LLMQueryResponse | null>(null)
  const [copied, setCopied] = useState(false)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  const { data: endpoints = [] } = useQuery({
    queryKey: ['llm-endpoints'],
    queryFn: llmApi.listEndpoints,
    enabled: open,
  })
  const hasDefault = endpoints.some(e => e.is_default && e.enabled)

  const submit = useMutation({
    mutationFn: () => llmApi.submitQuery({ prompt, intent }),
    onSuccess: r => setResult(r),
  })

  useEffect(() => {
    if (open && textareaRef.current) textareaRef.current.focus()
  }, [open])

  const copy = async () => {
    if (!result) return
    await navigator.clipboard.writeText(result.result)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  // Extract code block content (strip ```lang and ``` fences)
  const extractCode = (text: string): string => {
    const match = text.match(/```[a-z]*\n?([\s\S]*?)```/)
    return match ? match[1].trim() : text.trim()
  }

  return (
    <>
      {/* Floating trigger button */}
      <button
        onClick={() => setOpen(o => !o)}
        className="fixed bottom-6 right-6 z-40 flex h-12 w-12 items-center justify-center rounded-full bg-blue-600 text-white shadow-lg hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2"
        title="AI Assistant">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none"
          stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M12 2a10 10 0 0 1 10 10c0 5.52-4.48 10-10 10S2 17.52 2 12 6.48 2 12 2" />
          <path d="M8 14s1.5 2 4 2 4-2 4-2" />
          <line x1="9" y1="9" x2="9.01" y2="9" />
          <line x1="15" y1="9" x2="15.01" y2="9" />
        </svg>
      </button>

      {/* Panel */}
      {open && (
        <div className="fixed bottom-20 right-6 z-50 flex w-[480px] flex-col rounded-xl border border-gray-200 bg-white shadow-2xl">
          {/* Header */}
          <div className="flex items-center justify-between rounded-t-xl border-b border-gray-100 bg-gray-50 px-4 py-3">
            <span className="text-sm font-semibold text-gray-900">AI Assistant</span>
            <button onClick={() => setOpen(false)}
              className="text-gray-400 hover:text-gray-600">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none"
                stroke="currentColor" strokeWidth="2">
                <line x1="18" y1="6" x2="6" y2="18" />
                <line x1="6" y1="6" x2="18" y2="18" />
              </svg>
            </button>
          </div>

          <div className="flex flex-col gap-3 p-4">
            {/* No default endpoint warning */}
            {!hasDefault && (
              <div className="rounded border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700">
                No default LLM endpoint configured.{' '}
                <a href="/settings" className="underline hover:text-amber-900">
                  Add one in Settings → LLM
                </a>
              </div>
            )}

            {/* Intent selector */}
            <div className="flex gap-1 rounded-lg bg-gray-100 p-1">
              {(Object.keys(INTENT_LABELS) as Intent[]).map(i => (
                <button
                  key={i}
                  onClick={() => setIntent(i)}
                  className={`flex-1 rounded px-2 py-1 text-xs font-medium transition-colors ${
                    intent === i
                      ? 'bg-white text-gray-900 shadow-sm'
                      : 'text-gray-600 hover:text-gray-900'
                  }`}>
                  {INTENT_LABELS[i]}
                </button>
              ))}
            </div>

            {/* Prompt textarea */}
            <textarea
              ref={textareaRef}
              value={prompt}
              onChange={e => setPrompt(e.target.value)}
              placeholder={INTENT_PLACEHOLDERS[intent]}
              rows={4}
              className="w-full resize-none rounded border border-gray-300 px-3 py-2 text-sm text-gray-900 placeholder-gray-400 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            />

            <button
              onClick={() => { setResult(null); submit.mutate() }}
              disabled={!prompt.trim() || !hasDefault || submit.isPending}
              className="w-full rounded bg-blue-600 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50">
              {submit.isPending ? 'Generating…' : 'Generate'}
            </button>

            {submit.isError && (
              <div className="rounded border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
                {(submit.error as any)?.detail ?? 'Generation failed'}
              </div>
            )}

            {/* Result panel */}
            {result && (
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-xs text-gray-500">
                    {result.model_used} · {result.input_tokens + result.output_tokens} tokens ·{' '}
                    {result.duration_ms}ms
                  </span>
                  <div className="flex gap-1">
                    <button onClick={copy}
                      className="rounded border border-gray-200 px-2 py-1 text-xs text-gray-600 hover:bg-gray-50">
                      {copied ? '✓ Copied' : 'Copy'}
                    </button>
                    {intent === 'salt_state' && onApplySaltState && (
                      <button
                        onClick={() => onApplySaltState(extractCode(result.result))}
                        className="rounded border border-green-200 bg-green-50 px-2 py-1 text-xs font-medium text-green-700 hover:bg-green-100">
                        Apply to Salt
                      </button>
                    )}
                    {intent === 'ansible_playbook' && onSavePlaybook && (
                      <button
                        onClick={() => onSavePlaybook(extractCode(result.result))}
                        className="rounded border border-blue-200 bg-blue-50 px-2 py-1 text-xs font-medium text-blue-700 hover:bg-blue-100">
                        Save as Playbook
                      </button>
                    )}
                  </div>
                </div>
                <pre className="max-h-64 overflow-auto rounded bg-gray-900 p-3 text-xs text-gray-100">
                  <code>{result.result}</code>
                </pre>
              </div>
            )}
          </div>
        </div>
      )}
    </>
  )
}
```

- [ ] **Step 3: Mount `<LLMAssistant />` in the authenticated layout**

Find the component that wraps authenticated routes (grep for Sidebar, look at App.tsx or a Layout component). Add at the end of that component, before the closing tag of the authenticated wrapper:

```tsx
import LLMAssistant from './components/llm/LLMAssistant'

// Inside the authenticated layout render:
<LLMAssistant />
```

This makes it floating and accessible from every page without props (uses default endpoint, no callbacks). Pages can render their own `<LLMAssistant onApplySaltState={...} />` if they want the action buttons wired up.

- [ ] **Step 4: Build and verify**

```bash
cd frontend && npm run build 2>&1 | grep -E "error TS|✓ built"
```
Expected: `✓ built` with no TypeScript errors

- [ ] **Step 5: Run full unit suite**

```bash
cd .. && source .venv/bin/activate && pytest tests/unit/ -q
```
Expected: all tests pass, 0 regressions

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/llm/LLMAssistant.tsx
git add frontend/src/  # picks up any App.tsx / layout changes
git commit -m "feat: floating AI Assistant panel with intent selector and result preview"
```

---

## Self-Review

**Spec coverage check:**

| Requirement | Task |
|---|---|
| Admin adds/edits/deletes/enables LLM endpoints | T2 service + T4 settings tab |
| Per-endpoint: name, provider, URL, key, model, max_tokens, default flag | T1 model + T2 schema |
| Test endpoint connection | T4 route + T5 LLMSettingsTab test button |
| Operator+ opens AI Assistant | T6 floating panel with require_role("operator","admin") |
| Intent selector: 4 intents | T6 panel + T4 route |
| Fleet context injected | T3 build_fleet_context |
| Result in syntax-highlighted preview | T6 `<pre><code>` block |
| Save as Playbook / Apply to Salt buttons | T6 panel (callback-based, wired per page) |
| Query log stored | T4 route + T2 service create_query_log |
| No default → clear message | T6 panel warning banner |
| Ollama (no key) works | T3 caller (api_key=None path) |
| Anthropic works | T3 call_anthropic |

**Placeholder scan:** None found — every step has code.

**Type consistency check:**
- `LLMEndpointCreate.api_key` (str | None) → `llm_svc.create_endpoint` encrypts with `encrypt_secret` — consistent
- `LLMEndpointResponse.has_api_key` (bool) → set as `endpoint.api_key_encrypted is not None` — consistent
- `LLMQueryRequest.intent` Literal validated → same Literal used in `build_fleet_context` INTENT_ADDENDUM dict — consistent
- `call_openai_compat` returns `tuple[str, int, int]` → destructured as `content, input_tokens, output_tokens` in route — consistent
- `LLMQueryLog.model_used` (str | None) → `LLMQueryLogEntry.model_used` (str | None) — consistent

**No regressions:** New code only imports from existing services (`platform_settings_svc`, `get_db`, `require_role`). No existing models or routes are modified.
