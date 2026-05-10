# Fleet Platform — Plan 1: Foundation (DB + FastAPI Core + Auth)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up a working FastAPI application with complete PostgreSQL + TimescaleDB schema, JWT authentication, RBAC, and health endpoint — the foundation every subsequent plan builds on.

**Architecture:** FastAPI monolith with SQLAlchemy 2.0 async ORM using psycopg3. All 11 database tables created in a single Alembic migration including TimescaleDB hypertable conversion. pydantic-settings manages config. JWT HS256 with 15-min access / 7-day refresh tokens. RBAC enforced as FastAPI `Depends()` chains.

**Tech Stack:** Python 3.13, FastAPI 0.115, SQLAlchemy 2.0.36, Alembic 1.14, psycopg[async,binary] 3.2, pydantic v2, pydantic-settings 2.7, PyJWT 2.9, bcrypt 4.2, structlog 24, PostgreSQL 17 + TimescaleDB 2.18, Redis 7.4, Docker Compose v2, pytest 8.3, pytest-asyncio 0.24, httpx 0.28

---

## Scope

This is Plan 1 of 6. Subsequent plans:
- **Plan 2:** Salt returner + grain/execution ingest + Celery workers
- **Plan 3:** Fleet API — nodes, groups, tags, overview
- **Plan 4:** Drift engine — baseline loader, diff computation, drift API
- **Plan 5:** SBOM pipeline — Syft Salt state, ingest, search
- **Plan 6:** React frontend — all pages and components

When Plan 1 is complete you have: a `docker compose up` environment with PostgreSQL 17 + TimescaleDB running, all DB tables migrated, a FastAPI server returning `200` from `/health`, and a working `/auth/login` + `/auth/refresh` that issues JWTs with RBAC claims.

---

## File Map

```
macos-fleet-platform/
├── pyproject.toml
├── .env.example
├── .env                          # gitignored, copy of .env.example
├── .gitignore
├── alembic.ini
├── pytest.ini
├── deploy/
│   ├── docker-compose.yml
│   ├── docker-compose.override.yml
│   └── postgres-init/
│       └── 01-test-db.sh
├── platform/
│   ├── __init__.py
│   ├── api/
│   │   ├── __init__.py
│   │   ├── main.py               # FastAPI app factory + lifespan
│   │   ├── deps.py               # Shared FastAPI dependencies
│   │   └── routes/
│   │       ├── __init__.py
│   │       ├── health.py
│   │       └── auth.py
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py             # pydantic-settings
│   │   ├── auth.py               # JWT encode/decode + RBAC deps
│   │   └── logging.py            # structlog JSON config
│   ├── models/
│   │   ├── __init__.py
│   │   ├── base.py               # DeclarativeBase + TimestampMixin
│   │   ├── user.py
│   │   ├── node.py               # Node + Tag
│   │   ├── group.py              # Group + GroupMember
│   │   ├── facts.py              # NodeFact (hypertable)
│   │   ├── drift.py              # DesiredStateBaseline + DriftRecord (hypertable)
│   │   ├── sbom.py               # SBOMScan + SBOMComponent
│   │   ├── execution.py          # ExecutionJob + ExecutionResult
│   │   └── audit.py              # AuditEvent (hypertable)
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── common.py             # PaginatedResponse, ErrorResponse
│   │   └── auth.py               # LoginRequest, TokenResponse
│   └── db/
│       ├── __init__.py
│       ├── session.py            # async engine + session factory
│       └── migrations/
│           ├── env.py
│           ├── script.py.mako
│           └── versions/
│               └── 001_initial_schema.py
└── tests/
    ├── conftest.py               # shared fixtures: engine, session, client
    ├── unit/
    │   ├── __init__.py
    │   ├── test_config.py
    │   └── test_auth_core.py
    └── integration/
        ├── __init__.py
        ├── test_health.py
        └── test_auth_endpoints.py
```

---

## Task 1: Project scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `.env.example`
- Create: `.gitignore`
- Create: `pytest.ini`
- Create: all `__init__.py` files listed in the File Map

- [ ] **Step 1: Create pyproject.toml**

```toml
# pyproject.toml
[project]
name = "fleet-platform"
version = "0.1.0"
requires-python = ">=3.13"
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.32.0",
    "sqlalchemy>=2.0.36",
    "alembic>=1.14.0",
    "psycopg[async,binary]>=3.2.0",
    "pydantic>=2.10.0",
    "pydantic-settings>=2.7.0",
    "pyjwt[crypto]>=2.9.0",
    "bcrypt>=4.2.0",
    "celery[redis]>=5.4.0",
    "redis>=5.2.0",
    "structlog>=24.4.0",
    "python-multipart>=0.0.12",
    "httpx>=0.28.0",
    "slowapi>=0.1.9",
    "aiofiles>=24.1.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.3.0",
    "pytest-asyncio>=0.24.0",
    "pytest-cov>=6.0.0",
    "ruff>=0.8.0",
]

[tool.ruff]
line-length = 100
target-version = "py313"

[tool.ruff.lint]
select = ["E", "F", "I"]

[tool.ruff.lint.isort]
known-first-party = ["platform"]
```

- [ ] **Step 2: Create .env.example**

```bash
# .env.example
DATABASE_URL=postgresql+psycopg://fleet:fleet@localhost:5432/fleet_platform
TEST_DATABASE_URL=postgresql+psycopg://fleet:fleet@localhost:5432/fleet_test
REDIS_URL=redis://:redispass@localhost:6379/0
JWT_SECRET=change-me-generate-with-openssl-rand-hex-32
JWT_ALGORITHM=HS256
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=15
JWT_REFRESH_TOKEN_EXPIRE_DAYS=7
FRONTEND_ORIGIN=http://localhost:5173
ENVIRONMENT=development
```

- [ ] **Step 3: Create .gitignore**

```gitignore
# .gitignore
.env
.venv/
__pycache__/
*.pyc
*.pyo
.pytest_cache/
.ruff_cache/
htmlcov/
.coverage
dist/
*.egg-info/
```

- [ ] **Step 4: Create pytest.ini**

```ini
# pytest.ini
[pytest]
asyncio_mode = auto
testpaths = tests
addopts = -v --tb=short
```

- [ ] **Step 5: Create directory structure and empty __init__.py files**

```bash
mkdir -p platform/api/routes platform/core platform/models platform/schemas
mkdir -p platform/db/migrations/versions
mkdir -p tests/unit tests/integration
mkdir -p deploy/postgres-init

touch platform/__init__.py
touch platform/api/__init__.py platform/api/routes/__init__.py
touch platform/core/__init__.py
touch platform/models/__init__.py
touch platform/schemas/__init__.py
touch platform/db/__init__.py
touch tests/__init__.py tests/unit/__init__.py tests/integration/__init__.py
```

- [ ] **Step 6: Copy .env.example to .env and install dependencies**

```bash
cp .env.example .env
uv sync --dev
# or: pip install -e ".[dev]"
```

Expected: no errors. `.venv/` created (or packages installed).

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml .env.example .gitignore pytest.ini platform/ tests/ deploy/
git commit -m "feat: project scaffolding — pyproject, directory structure, pytest config"
```

---

## Task 2: Docker Compose infrastructure

**Files:**
- Create: `deploy/docker-compose.yml`
- Create: `deploy/docker-compose.override.yml`
- Create: `deploy/postgres-init/01-test-db.sh`

- [ ] **Step 1: Write docker-compose.yml**

```yaml
# deploy/docker-compose.yml
services:
  postgres:
    image: timescale/timescaledb:latest-pg17
    environment:
      POSTGRES_DB: fleet_platform
      POSTGRES_USER: fleet
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-fleet}
    volumes:
      - pgdata:/var/lib/postgresql/data
    ports:
      - "5432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U fleet -d fleet_platform"]
      interval: 5s
      timeout: 3s
      retries: 15

  redis:
    image: redis:7.4-alpine
    command: redis-server --requirepass ${REDIS_PASSWORD:-redispass} --appendonly yes
    volumes:
      - redisdata:/data
    ports:
      - "6379:6379"
    healthcheck:
      test: ["CMD", "redis-cli", "--no-auth-warning", "-a", "${REDIS_PASSWORD:-redispass}", "ping"]
      interval: 5s
      timeout: 3s
      retries: 10

volumes:
  pgdata:
  redisdata:
```

- [ ] **Step 2: Write docker-compose.override.yml (adds test DB init)**

```yaml
# deploy/docker-compose.override.yml
services:
  postgres:
    volumes:
      - pgdata:/var/lib/postgresql/data
      - ./postgres-init:/docker-entrypoint-initdb.d
```

- [ ] **Step 3: Write the test DB init script**

```bash
#!/bin/bash
# deploy/postgres-init/01-test-db.sh
set -e
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE DATABASE fleet_test;
    GRANT ALL PRIVILEGES ON DATABASE fleet_test TO $POSTGRES_USER;
    \c fleet_test
    CREATE EXTENSION IF NOT EXISTS timescaledb;
    CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
EOSQL
```

```bash
chmod +x deploy/postgres-init/01-test-db.sh
```

- [ ] **Step 4: Start infrastructure**

```bash
cd deploy
docker compose up -d
```

Expected:
```
✔ Container deploy-postgres-1  Healthy
✔ Container deploy-redis-1     Healthy
```

- [ ] **Step 5: Verify TimescaleDB is installed**

```bash
docker exec deploy-postgres-1 psql -U fleet -d fleet_platform \
  -c "SELECT extname, extversion FROM pg_extension WHERE extname = 'timescaledb';"
```

Expected:
```
   extname   | extversion
-------------+------------
 timescaledb | 2.x.x
(1 row)
```

- [ ] **Step 6: Verify test database exists**

```bash
docker exec deploy-postgres-1 psql -U fleet -d fleet_test \
  -c "SELECT extname FROM pg_extension WHERE extname = 'timescaledb';"
```

Expected: `(1 row)` with `timescaledb`.

- [ ] **Step 7: Commit**

```bash
git add deploy/
git commit -m "feat: docker compose — postgres 17+timescaledb 2.x, redis 7.4, test DB init"
```

---

## Task 3: Config and DB session

**Files:**
- Create: `platform/core/config.py`
- Create: `platform/db/session.py`
- Create: `tests/unit/test_config.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_config.py
from platform.core.config import Settings


def test_defaults_are_sane():
    s = Settings()
    assert s.jwt_algorithm == "HS256"
    assert s.jwt_access_token_expire_minutes == 15
    assert s.jwt_refresh_token_expire_days == 7
    assert s.environment == "development"
    assert s.is_development is True


def test_is_development_false_in_production(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    s = Settings()
    assert s.is_development is False


def test_database_url_is_set():
    s = Settings()
    assert "postgresql" in s.database_url
    assert "fleet_platform" in s.database_url
```

- [ ] **Step 2: Run test — expect failure (ImportError)**

```bash
pytest tests/unit/test_config.py -v
```

Expected: `ImportError: No module named 'platform.core.config'`

- [ ] **Step 3: Implement platform/core/config.py**

```python
# platform/core/config.py
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://fleet:fleet@localhost:5432/fleet_platform"
    test_database_url: str = "postgresql+psycopg://fleet:fleet@localhost:5432/fleet_test"
    redis_url: str = "redis://:redispass@localhost:6379/0"

    jwt_secret: str = "insecure-dev-secret"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 15
    jwt_refresh_token_expire_days: int = 7

    frontend_origin: str = "http://localhost:5173"
    environment: str = "development"

    @property
    def is_development(self) -> bool:
        return self.environment == "development"


settings = Settings()
```

- [ ] **Step 4: Run test — expect pass**

```bash
pytest tests/unit/test_config.py -v
```

Expected:
```
PASSED tests/unit/test_config.py::test_defaults_are_sane
PASSED tests/unit/test_config.py::test_is_development_false_in_production
PASSED tests/unit/test_config.py::test_database_url_is_set
3 passed
```

- [ ] **Step 5: Write platform/db/session.py**

No test needed here — session is infrastructure, tested via integration tests later.

```python
# platform/db/session.py
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from platform.core.config import settings

engine = create_async_engine(
    settings.database_url,
    echo=settings.is_development,
    pool_size=10,
    max_overflow=20,
    pool_timeout=30,
    pool_pre_ping=True,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
```

- [ ] **Step 6: Commit**

```bash
git add platform/core/config.py platform/db/session.py tests/unit/test_config.py
git commit -m "feat: pydantic-settings config + async SQLAlchemy session"
```

---

## Task 4: SQLAlchemy models — all tables

**Files:**
- Create: `platform/models/base.py`
- Create: `platform/models/user.py`
- Create: `platform/models/node.py`
- Create: `platform/models/group.py`
- Create: `platform/models/facts.py`
- Create: `platform/models/drift.py`
- Create: `platform/models/sbom.py`
- Create: `platform/models/execution.py`
- Create: `platform/models/audit.py`
- Modify: `platform/models/__init__.py`

No unit tests for models — they're verified by the Alembic migration in Task 5.

- [ ] **Step 1: Write models/base.py**

```python
# platform/models/base.py
from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
```

- [ ] **Step 2: Write models/user.py**

```python
# platform/models/user.py
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from platform.models.base import Base, TimestampMixin


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="viewer")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
```

- [ ] **Step 3: Write models/node.py**

```python
# platform/models/node.py
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Index, Numeric, SmallInteger, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import INET, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from platform.models.base import Base, TimestampMixin


class Node(Base, TimestampMixin):
    __tablename__ = "nodes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    minion_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    hostname: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(INET, nullable=True)
    os_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    os_build: Mapped[str | None] = mapped_column(String(50), nullable=True)
    hardware_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    cpu_cores: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    ram_gb: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    storage_gb: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="unknown")
    drift_score: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    node_token_hash: Mapped[str] = mapped_column(String(72), nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    tags: Mapped[list["Tag"]] = relationship(
        "Tag", back_populates="node", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("idx_nodes_status", "status"),
        Index("idx_nodes_drift_score", "drift_score"),
        Index("idx_nodes_last_seen", "last_seen_at"),
    )


class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    node_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("nodes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    key: Mapped[str] = mapped_column(String(100), nullable=False)
    value: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    node: Mapped["Node"] = relationship("Node", back_populates="tags")

    __table_args__ = (
        UniqueConstraint("node_id", "key", name="uq_tags_node_key"),
        Index("idx_tags_key_value", "key", "value"),
    )
```

- [ ] **Step 4: Write models/group.py**

```python
# platform/models/group.py
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from platform.models.base import Base, TimestampMixin


class Group(Base, TimestampMixin):
    __tablename__ = "groups"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    type: Mapped[str] = mapped_column(String(20), nullable=False)  # static | dynamic
    predicate: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class GroupMember(Base):
    __tablename__ = "group_members"

    group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("groups.id", ondelete="CASCADE"),
        primary_key=True,
    )
    node_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("nodes.id", ondelete="CASCADE"),
        primary_key=True,
    )
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
```

- [ ] **Step 5: Write models/facts.py**

```python
# platform/models/facts.py
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from platform.models.base import Base


class NodeFact(Base):
    """TimescaleDB hypertable — partition key: collected_at"""

    __tablename__ = "node_facts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    node_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("nodes.id"), nullable=False
    )
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, primary_key=True
    )
    grains: Mapped[dict] = mapped_column(JSONB, nullable=False)

    __table_args__ = (
        Index("idx_node_facts_node_id", "node_id", "collected_at"),
    )
```

- [ ] **Step 6: Write models/drift.py**

```python
# platform/models/drift.py
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, SmallInteger, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from platform.models.base import Base, TimestampMixin


class DesiredStateBaseline(Base, TimestampMixin):
    __tablename__ = "desired_state_baselines"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_type: Mapped[str] = mapped_column(String(20), nullable=False)  # group|node|global
    target_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    git_commit_sha: Mapped[str] = mapped_column(String(40), nullable=False)
    state_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class DriftRecord(Base):
    """TimescaleDB hypertable — partition key: computed_at"""

    __tablename__ = "drift_records"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    node_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("nodes.id"), nullable=False
    )
    baseline_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("desired_state_baselines.id", ondelete="SET NULL"),
        nullable=True,
    )
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, primary_key=True
    )
    drift_score: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    missing_packages: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    extra_packages: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    version_mismatches: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    service_drift: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    config_drift: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    __table_args__ = (
        Index("idx_drift_records_node_id", "node_id", "computed_at"),
        Index("idx_drift_records_score", "drift_score", "computed_at"),
    )
```

- [ ] **Step 7: Write models/sbom.py**

```python
# platform/models/sbom.py
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from platform.models.base import Base


class SBOMScan(Base):
    __tablename__ = "sbom_scans"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    node_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    syft_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    format: Mapped[str] = mapped_column(String(20), nullable=False, default="cyclonedx")
    scanned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    component_count: Mapped[int | None] = mapped_column(Integer, nullable=True)


class SBOMComponent(Base):
    __tablename__ = "sbom_components"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    scan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sbom_scans.id", ondelete="CASCADE"), nullable=False
    )
    node_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    purl: Mapped[str | None] = mapped_column(String(500), nullable=True)
    component_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    licenses: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    cpes: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    # search_vector is added as a GENERATED column via raw SQL in the migration

    __table_args__ = (
        Index("idx_sbom_components_node_id", "node_id"),
        Index("idx_sbom_components_name", "name"),
        Index("idx_sbom_components_purl", "purl"),
    )
```

- [ ] **Step 8: Write models/execution.py**

```python
# platform/models/execution.py
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from platform.models.base import Base


class ExecutionJob(Base):
    __tablename__ = "execution_jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    salt_jid: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    target_type: Mapped[str] = mapped_column(String(20), nullable=False)
    target_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    triggered_by: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)

    __table_args__ = (
        Index("idx_exec_jobs_status", "status", "started_at"),
    )


class ExecutionResult(Base):
    __tablename__ = "execution_results"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("execution_jobs.id", ondelete="CASCADE"), nullable=False
    )
    node_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("nodes.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stdout: Mapped[str | None] = mapped_column(Text, nullable=True)
    stderr: Mapped[str | None] = mapped_column(Text, nullable=True)
    changes: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("idx_exec_results_job_id", "job_id"),
        Index("idx_exec_results_node_id", "node_id", "completed_at"),
    )
```

- [ ] **Step 9: Write models/audit.py**

```python
# platform/models/audit.py
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, String
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from platform.models.base import Base


class AuditEvent(Base):
    """TimescaleDB hypertable — partition key: event_at"""

    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, primary_key=True
    )
    actor: Mapped[str] = mapped_column(String(255), nullable=False)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    resource_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    old_value: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    new_value: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(INET, nullable=True)

    __table_args__ = (
        Index("idx_audit_events_actor", "actor", "event_at"),
        Index("idx_audit_events_resource", "resource_type", "resource_id", "event_at"),
    )
```

- [ ] **Step 10: Update models/__init__.py to import all models**

```python
# platform/models/__init__.py
from platform.models.base import Base, TimestampMixin
from platform.models.user import User
from platform.models.node import Node, Tag
from platform.models.group import Group, GroupMember
from platform.models.facts import NodeFact
from platform.models.drift import DesiredStateBaseline, DriftRecord
from platform.models.sbom import SBOMScan, SBOMComponent
from platform.models.execution import ExecutionJob, ExecutionResult
from platform.models.audit import AuditEvent

__all__ = [
    "Base", "TimestampMixin",
    "User",
    "Node", "Tag",
    "Group", "GroupMember",
    "NodeFact",
    "DesiredStateBaseline", "DriftRecord",
    "SBOMScan", "SBOMComponent",
    "ExecutionJob", "ExecutionResult",
    "AuditEvent",
]
```

- [ ] **Step 11: Verify models import cleanly**

```bash
python -c "from platform.models import Base; print('OK:', len(Base.metadata.tables), 'tables')"
```

Expected:
```
OK: 11 tables
```

- [ ] **Step 12: Commit**

```bash
git add platform/models/
git commit -m "feat: SQLAlchemy 2.0 models — 11 tables (nodes, groups, facts, drift, sbom, exec, audit)"
```

---

## Task 5: Alembic setup and initial migration

**Files:**
- Create: `alembic.ini`
- Create: `platform/db/migrations/env.py`
- Create: `platform/db/migrations/script.py.mako`
- Create: `platform/db/migrations/versions/001_initial_schema.py`

- [ ] **Step 1: Initialize Alembic**

```bash
alembic init platform/db/migrations
```

This creates `alembic.ini` and `platform/db/migrations/env.py`. We'll overwrite both.

- [ ] **Step 2: Write alembic.ini**

```ini
# alembic.ini
[alembic]
script_location = platform/db/migrations
prepend_sys_path = .
version_path_separator = os
sqlalchemy.url = postgresql+psycopg://fleet:fleet@localhost:5432/fleet_platform

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARN
handlers = console
qualname =

[logger_sqlalchemy]
level = WARN
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
datefmt = %H:%M:%S
```

- [ ] **Step 3: Write migrations/env.py**

```python
# platform/db/migrations/env.py
import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from platform.models import Base  # imports all models

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

- [ ] **Step 4: Write the initial migration**

```python
# platform/db/migrations/versions/001_initial_schema.py
"""Initial schema — all tables + TimescaleDB hypertables

Revision ID: 001
Revises:
Create Date: 2026-05-09
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Enable extensions ────────────────────────────────────────────
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE")
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')

    # ── users ────────────────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("email", sa.String(255), unique=True, nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", sa.String(20), nullable=False, server_default="viewer"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_users_email", "users", ["email"])

    # ── nodes ────────────────────────────────────────────────────────
    op.create_table(
        "nodes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("minion_id", sa.String(255), unique=True, nullable=False),
        sa.Column("hostname", sa.String(255), nullable=True),
        sa.Column("ip_address", postgresql.INET, nullable=True),
        sa.Column("os_version", sa.String(50), nullable=True),
        sa.Column("os_build", sa.String(50), nullable=True),
        sa.Column("hardware_model", sa.String(100), nullable=True),
        sa.Column("cpu_cores", sa.SmallInteger, nullable=True),
        sa.Column("ram_gb", sa.Numeric(8, 2), nullable=True),
        sa.Column("storage_gb", sa.Numeric(10, 2), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="unknown"),
        sa.Column("drift_score", sa.SmallInteger, nullable=False, server_default="0"),
        sa.Column("node_token_hash", sa.String(72), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_nodes_status", "nodes", ["status"])
    op.create_index("idx_nodes_drift_score", "nodes", ["drift_score"])
    op.create_index("idx_nodes_last_seen", "nodes", ["last_seen_at"])

    # ── tags ─────────────────────────────────────────────────────────
    op.create_table(
        "tags",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("node_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("key", sa.String(100), nullable=False),
        sa.Column("value", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("node_id", "key", name="uq_tags_node_key"),
    )
    op.create_index("idx_tags_node_id", "tags", ["node_id"])
    op.create_index("idx_tags_key_value", "tags", ["key", "value"])

    # ── groups ───────────────────────────────────────────────────────
    op.create_table(
        "groups",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(100), unique=True, nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("type", sa.String(20), nullable=False),
        sa.Column("predicate", postgresql.JSONB, nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # ── group_members ────────────────────────────────────────────────
    op.create_table(
        "group_members",
        sa.Column("group_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("node_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("nodes.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("idx_group_members_node_id", "group_members", ["node_id"])

    # ── node_facts (TimescaleDB hypertable) ──────────────────────────
    op.create_table(
        "node_facts",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("node_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("nodes.id"), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False, primary_key=True),
        sa.Column("grains", postgresql.JSONB, nullable=False),
    )
    op.create_index("idx_node_facts_node_id", "node_facts", ["node_id", "collected_at"])
    op.execute(
        "SELECT create_hypertable('node_facts', by_range('collected_at', INTERVAL '1 day'))"
    )
    op.execute(
        "SELECT add_retention_policy('node_facts', INTERVAL '90 days')"
    )

    # ── desired_state_baselines ──────────────────────────────────────
    op.create_table(
        "desired_state_baselines",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("target_type", sa.String(20), nullable=False),
        sa.Column("target_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("git_commit_sha", sa.String(40), nullable=False),
        sa.Column("state_json", postgresql.JSONB, nullable=False),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # ── drift_records (TimescaleDB hypertable) ───────────────────────
    op.create_table(
        "drift_records",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("node_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("nodes.id"), nullable=False),
        sa.Column("baseline_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("desired_state_baselines.id", ondelete="SET NULL"), nullable=True),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False, primary_key=True),
        sa.Column("drift_score", sa.SmallInteger, nullable=False),
        sa.Column("missing_packages", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("extra_packages", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("version_mismatches", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("service_drift", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("config_drift", postgresql.JSONB, nullable=False, server_default="[]"),
    )
    op.create_index("idx_drift_records_node_id", "drift_records", ["node_id", "computed_at"])
    op.create_index("idx_drift_records_score", "drift_records", ["drift_score", "computed_at"])
    op.execute(
        "SELECT create_hypertable('drift_records', by_range('computed_at', INTERVAL '1 day'))"
    )
    op.execute(
        "SELECT add_retention_policy('drift_records', INTERVAL '180 days')"
    )

    # ── sbom_scans ───────────────────────────────────────────────────
    op.create_table(
        "sbom_scans",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("node_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("syft_version", sa.String(20), nullable=True),
        sa.Column("format", sa.String(20), nullable=False, server_default="cyclonedx"),
        sa.Column("scanned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("component_count", sa.Integer, nullable=True),
    )
    op.create_index("idx_sbom_scans_node_id", "sbom_scans", ["node_id", "scanned_at"])

    # ── sbom_components ──────────────────────────────────────────────
    op.create_table(
        "sbom_components",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("scan_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sbom_scans.id", ondelete="CASCADE"), nullable=False),
        sa.Column("node_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("version", sa.String(100), nullable=True),
        sa.Column("purl", sa.String(500), nullable=True),
        sa.Column("component_type", sa.String(50), nullable=True),
        sa.Column("licenses", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("cpes", postgresql.JSONB, nullable=False, server_default="[]"),
    )
    # Generated tsvector column for full-text search
    op.execute("""
        ALTER TABLE sbom_components
        ADD COLUMN search_vector tsvector
        GENERATED ALWAYS AS (
            to_tsvector('english',
                name || ' ' ||
                COALESCE(version, '') || ' ' ||
                COALESCE(purl, '')
            )
        ) STORED
    """)
    op.create_index("idx_sbom_components_search", "sbom_components", ["search_vector"], postgresql_using="gin")
    op.create_index("idx_sbom_components_node_id", "sbom_components", ["node_id"])
    op.create_index("idx_sbom_components_name", "sbom_components", ["name"])
    op.create_index("idx_sbom_components_purl", "sbom_components", ["purl"])

    # ── execution_jobs ───────────────────────────────────────────────
    op.create_table(
        "execution_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("salt_jid", sa.String(100), nullable=True),
        sa.Column("type", sa.String(50), nullable=False),
        sa.Column("target_type", sa.String(20), nullable=False),
        sa.Column("target_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("triggered_by", sa.String(255), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata", postgresql.JSONB, nullable=False, server_default="{}"),
    )
    op.create_index("idx_exec_jobs_status", "execution_jobs", ["status", "started_at"])
    op.create_index("idx_exec_jobs_salt_jid", "execution_jobs", ["salt_jid"])

    # ── execution_results ────────────────────────────────────────────
    op.create_table(
        "execution_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("execution_jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("node_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("nodes.id"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("exit_code", sa.Integer, nullable=True),
        sa.Column("stdout", sa.Text, nullable=True),
        sa.Column("stderr", sa.Text, nullable=True),
        sa.Column("changes", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("idx_exec_results_job_id", "execution_results", ["job_id"])
    op.create_index("idx_exec_results_node_id", "execution_results", ["node_id", "completed_at"])

    # ── audit_events (TimescaleDB hypertable) ────────────────────────
    op.create_table(
        "audit_events",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("event_at", sa.DateTime(timezone=True), nullable=False, primary_key=True),
        sa.Column("actor", sa.String(255), nullable=False),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("resource_type", sa.String(50), nullable=True),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("old_value", postgresql.JSONB, nullable=True),
        sa.Column("new_value", postgresql.JSONB, nullable=True),
        sa.Column("ip_address", postgresql.INET, nullable=True),
    )
    op.create_index("idx_audit_events_actor", "audit_events", ["actor", "event_at"])
    op.create_index("idx_audit_events_resource", "audit_events", ["resource_type", "resource_id", "event_at"])
    op.execute(
        "SELECT create_hypertable('audit_events', by_range('event_at', INTERVAL '7 days'))"
    )
    op.execute(
        "SELECT add_retention_policy('audit_events', INTERVAL '730 days')"
    )

    # ── Fleet drift hourly continuous aggregate ──────────────────────
    op.execute("""
        CREATE MATERIALIZED VIEW fleet_drift_hourly
        WITH (timescaledb.continuous) AS
        SELECT
            time_bucket('1 hour', computed_at) AS bucket,
            AVG(drift_score)::SMALLINT AS avg_drift_score,
            MAX(drift_score) AS max_drift_score,
            COUNT(*) FILTER (WHERE drift_score > 50) AS nodes_high_drift,
            COUNT(DISTINCT node_id) AS nodes_evaluated
        FROM drift_records
        GROUP BY bucket
        WITH NO DATA
    """)
    op.execute("""
        SELECT add_continuous_aggregate_policy('fleet_drift_hourly',
            start_offset => INTERVAL '3 hours',
            end_offset   => INTERVAL '1 hour',
            schedule_interval => INTERVAL '1 hour')
    """)


def downgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW IF EXISTS fleet_drift_hourly")
    op.drop_table("audit_events")
    op.drop_table("execution_results")
    op.drop_table("execution_jobs")
    op.drop_table("sbom_components")
    op.drop_table("sbom_scans")
    op.drop_table("drift_records")
    op.drop_table("desired_state_baselines")
    op.drop_table("node_facts")
    op.drop_table("group_members")
    op.drop_table("groups")
    op.drop_table("tags")
    op.drop_table("nodes")
    op.drop_table("users")
```

- [ ] **Step 5: Run the migration**

```bash
alembic upgrade head
```

Expected output:
```
INFO  [alembic.runtime.migration] Running upgrade  -> 001, Initial schema — all tables + TimescaleDB hypertables
```

No errors. If you see `timescaledb: extension not available`, confirm Docker is running and the connection string is correct.

- [ ] **Step 6: Verify tables were created**

```bash
docker exec deploy-postgres-1 psql -U fleet -d fleet_platform \
  -c "\dt" | grep -E "nodes|tags|groups|drift|sbom|exec|audit|users|facts"
```

Expected: 11 table names listed.

- [ ] **Step 7: Verify hypertables**

```bash
docker exec deploy-postgres-1 psql -U fleet -d fleet_platform \
  -c "SELECT hypertable_name FROM timescaledb_information.hypertables;"
```

Expected:
```
 hypertable_name
-----------------
 node_facts
 drift_records
 audit_events
(3 rows)
```

- [ ] **Step 8: Commit**

```bash
git add alembic.ini platform/db/migrations/
git commit -m "feat: alembic migration 001 — full schema + timescaledb hypertables + continuous aggregate"
```

---

## Task 6: structlog logging

**Files:**
- Create: `platform/core/logging.py`

- [ ] **Step 1: Write platform/core/logging.py**

```python
# platform/core/logging.py
import logging
import structlog


def configure_logging(level: str = "INFO") -> None:
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelName(level)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

    logging.basicConfig(
        format="%(message)s",
        level=logging.getLevelName(level),
    )


def get_logger(name: str = __name__):
    return structlog.get_logger(name)
```

- [ ] **Step 2: Quick smoke test**

```bash
python -c "
from platform.core.logging import configure_logging, get_logger
configure_logging()
log = get_logger('smoke')
log.info('logging works', test=True)
"
```

Expected: JSON line printed to stdout with `level`, `event`, `test`, `timestamp` fields.

- [ ] **Step 3: Commit**

```bash
git add platform/core/logging.py
git commit -m "feat: structlog 24 JSON logging"
```

---

## Task 7: JWT auth core + RBAC

**Files:**
- Create: `platform/core/auth.py`
- Create: `tests/unit/test_auth_core.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_auth_core.py
import pytest
from datetime import timedelta

from platform.core.auth import (
    hash_password,
    verify_password,
    create_access_token,
    create_refresh_token,
    decode_token,
    TokenExpiredError,
    TokenInvalidError,
)


def test_password_hash_and_verify():
    hashed = hash_password("mysecret")
    assert hashed != "mysecret"
    assert verify_password("mysecret", hashed) is True
    assert verify_password("wrong", hashed) is False


def test_create_and_decode_access_token():
    token = create_access_token(user_id="user-123", email="a@b.com", role="viewer")
    claims = decode_token(token)
    assert claims["sub"] == "user-123"
    assert claims["email"] == "a@b.com"
    assert claims["role"] == "viewer"
    assert claims["type"] == "access"


def test_create_and_decode_refresh_token():
    token = create_refresh_token(user_id="user-123")
    claims = decode_token(token)
    assert claims["sub"] == "user-123"
    assert claims["type"] == "refresh"


def test_expired_token_raises():
    token = create_access_token(
        user_id="user-123", email="a@b.com", role="viewer",
        expires_delta=timedelta(seconds=-1)
    )
    with pytest.raises(TokenExpiredError):
        decode_token(token)


def test_invalid_token_raises():
    with pytest.raises(TokenInvalidError):
        decode_token("not.a.valid.token")
```

- [ ] **Step 2: Run tests — expect ImportError**

```bash
pytest tests/unit/test_auth_core.py -v
```

Expected: `ImportError: cannot import name 'hash_password' from 'platform.core.auth'`

- [ ] **Step 3: Implement platform/core/auth.py**

```python
# platform/core/auth.py
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from platform.core.config import settings


class TokenExpiredError(Exception):
    pass


class TokenInvalidError(Exception):
    pass


# ── Password hashing ──────────────────────────────────────────────────

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())


# ── Token creation ────────────────────────────────────────────────────

def create_access_token(
    user_id: str,
    email: str,
    role: str,
    expires_delta: timedelta | None = None,
) -> str:
    expire = datetime.now(UTC) + (
        expires_delta
        or timedelta(minutes=settings.jwt_access_token_expire_minutes)
    )
    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
        "type": "access",
        "exp": expire,
        "iat": datetime.now(UTC),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_refresh_token(user_id: str) -> str:
    expire = datetime.now(UTC) + timedelta(days=settings.jwt_refresh_token_expire_days)
    payload = {
        "sub": user_id,
        "type": "refresh",
        "exp": expire,
        "iat": datetime.now(UTC),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


# ── Token decoding ────────────────────────────────────────────────────

def decode_token(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.ExpiredSignatureError:
        raise TokenExpiredError("Token has expired")
    except jwt.PyJWTError:
        raise TokenInvalidError("Token is invalid")


# ── FastAPI dependencies ──────────────────────────────────────────────

_bearer = HTTPBearer(auto_error=False)


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> dict[str, Any]:
    if not credentials:
        raise _unauthorized("Missing Authorization header")
    try:
        claims = decode_token(credentials.credentials)
    except TokenExpiredError:
        raise _unauthorized("Token has expired")
    except TokenInvalidError:
        raise _unauthorized("Invalid token")
    if claims.get("type") != "access":
        raise _unauthorized("Refresh tokens cannot access this endpoint")
    return claims


def require_role(*roles: str):
    """FastAPI dependency factory. Usage: Depends(require_role('admin', 'operator'))"""

    async def dependency(claims: dict = Depends(get_current_user)) -> dict:
        if claims.get("role") not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{claims.get('role')}' cannot access this endpoint",
            )
        return claims

    return dependency
```

- [ ] **Step 4: Run tests — expect all pass**

```bash
pytest tests/unit/test_auth_core.py -v
```

Expected:
```
PASSED tests/unit/test_auth_core.py::test_password_hash_and_verify
PASSED tests/unit/test_auth_core.py::test_create_and_decode_access_token
PASSED tests/unit/test_auth_core.py::test_create_and_decode_refresh_token
PASSED tests/unit/test_auth_core.py::test_expired_token_raises
PASSED tests/unit/test_auth_core.py::test_invalid_token_raises
5 passed
```

- [ ] **Step 5: Commit**

```bash
git add platform/core/auth.py tests/unit/test_auth_core.py
git commit -m "feat: JWT auth core — hash_password, create_access_token, decode_token, RBAC deps"
```

---

## Task 8: FastAPI app + health endpoint

**Files:**
- Create: `platform/api/main.py`
- Create: `platform/api/deps.py`
- Create: `platform/api/routes/health.py`
- Create: `platform/schemas/common.py`
- Create: `tests/conftest.py`
- Create: `tests/integration/test_health.py`

- [ ] **Step 1: Write the failing integration test**

```python
# tests/integration/test_health.py
import pytest
from httpx import AsyncClient


async def test_health_returns_200(client: AsyncClient):
    response = await client.get("/health")
    assert response.status_code == 200


async def test_health_body(client: AsyncClient):
    response = await client.get("/health")
    data = response.json()
    assert data["status"] == "ok"
    assert "version" in data
    assert "environment" in data
```

- [ ] **Step 2: Write tests/conftest.py**

```python
# tests/conftest.py
import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
async def client():
    from platform.api.main import create_app
    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as ac:
        yield ac
```

- [ ] **Step 3: Run tests — expect ImportError**

```bash
pytest tests/integration/test_health.py -v
```

Expected: `ImportError: cannot import name 'create_app' from 'platform.api.main'`

- [ ] **Step 4: Write platform/schemas/common.py**

```python
# platform/schemas/common.py
from typing import Generic, TypeVar
from pydantic import BaseModel

T = TypeVar("T")


class PaginatedResponse(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    per_page: int


class ErrorDetail(BaseModel):
    code: str
    message: str
    request_id: str | None = None


class ErrorResponse(BaseModel):
    error: ErrorDetail
```

- [ ] **Step 5: Write platform/api/routes/health.py**

```python
# platform/api/routes/health.py
from fastapi import APIRouter
from platform.core.config import settings

router = APIRouter()


@router.get("/health")
async def health():
    return {
        "status": "ok",
        "version": "0.1.0",
        "environment": settings.environment,
    }
```

- [ ] **Step 6: Write platform/api/deps.py**

```python
# platform/api/deps.py
from collections.abc import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession
from platform.db.session import AsyncSessionLocal


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
```

- [ ] **Step 7: Write platform/api/main.py**

```python
# platform/api/main.py
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from platform.core.config import settings
from platform.core.logging import configure_logging
from platform.api.routes import health


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="Fleet Platform API",
        version="0.1.0",
        docs_url="/docs" if settings.is_development else None,
        redoc_url="/redoc" if settings.is_development else None,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_origin],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-Node-Token"],
    )

    app.include_router(health.router, tags=["health"])

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "INTERNAL_ERROR", "message": "An unexpected error occurred"}},
        )

    return app


app = create_app()
```

- [ ] **Step 8: Run integration tests — expect pass**

```bash
pytest tests/integration/test_health.py -v
```

Expected:
```
PASSED tests/integration/test_health.py::test_health_returns_200
PASSED tests/integration/test_health.py::test_health_body
2 passed
```

- [ ] **Step 9: Commit**

```bash
git add platform/api/ platform/schemas/common.py tests/conftest.py tests/integration/test_health.py
git commit -m "feat: FastAPI app factory + health endpoint + integration test fixture"
```

---

## Task 9: Login and refresh endpoints

**Files:**
- Create: `platform/schemas/auth.py`
- Create: `platform/api/routes/auth.py`
- Create: `tests/integration/test_auth_endpoints.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/integration/test_auth_endpoints.py
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from platform.core.auth import hash_password
from platform.core.config import settings
from platform.models import Base, User


@pytest.fixture(scope="session")
async def test_engine():
    engine = create_async_engine(settings.test_database_url, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def db_session(test_engine):
    async_session = async_sessionmaker(test_engine, expire_on_commit=False)
    async with async_session() as session:
        yield session
        await session.rollback()


@pytest.fixture
async def test_user(db_session: AsyncSession):
    user = User(
        email="test@fleet.local",
        password_hash=hash_password("password123"),
        role="operator",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    yield user
    await db_session.delete(user)
    await db_session.commit()


@pytest.fixture
async def auth_client(test_engine):
    from platform.api.main import create_app
    from platform.api import deps
    from platform.db.session import AsyncSessionLocal

    app = create_app()
    TestSessionLocal = async_sessionmaker(test_engine, expire_on_commit=False)

    async def override_get_db():
        async with TestSessionLocal() as session:
            yield session

    app.dependency_overrides[deps.get_db] = override_get_db

    from httpx import ASGITransport, AsyncClient
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as ac:
        yield ac


async def test_login_success(auth_client: AsyncClient, test_user: User):
    response = await auth_client.post("/auth/login", json={
        "email": "test@fleet.local",
        "password": "password123",
    })
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"


async def test_login_wrong_password(auth_client: AsyncClient, test_user: User):
    response = await auth_client.post("/auth/login", json={
        "email": "test@fleet.local",
        "password": "wrongpassword",
    })
    assert response.status_code == 401


async def test_login_unknown_email(auth_client: AsyncClient):
    response = await auth_client.post("/auth/login", json={
        "email": "nobody@fleet.local",
        "password": "password123",
    })
    assert response.status_code == 401


async def test_refresh_token(auth_client: AsyncClient, test_user: User):
    login = await auth_client.post("/auth/login", json={
        "email": "test@fleet.local",
        "password": "password123",
    })
    refresh_token = login.json()["refresh_token"]

    response = await auth_client.post("/auth/refresh", json={"refresh_token": refresh_token})
    assert response.status_code == 200
    assert "access_token" in response.json()


async def test_protected_endpoint_without_token(auth_client: AsyncClient):
    response = await auth_client.get("/auth/me")
    assert response.status_code == 401


async def test_protected_endpoint_with_valid_token(auth_client: AsyncClient, test_user: User):
    login = await auth_client.post("/auth/login", json={
        "email": "test@fleet.local",
        "password": "password123",
    })
    token = login.json()["access_token"]
    response = await auth_client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == "test@fleet.local"
    assert data["role"] == "operator"
```

- [ ] **Step 2: Run tests — expect ImportError**

```bash
pytest tests/integration/test_auth_endpoints.py -v
```

Expected: `ImportError` or `404` for `/auth/login`.

- [ ] **Step 3: Write platform/schemas/auth.py**

```python
# platform/schemas/auth.py
from pydantic import BaseModel, EmailStr


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class AccessTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class MeResponse(BaseModel):
    id: str
    email: str
    role: str
```

- [ ] **Step 4: Write platform/api/routes/auth.py**

```python
# platform/api/routes/auth.py
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from platform.api.deps import get_db
from platform.core.auth import (
    TokenExpiredError,
    TokenInvalidError,
    create_access_token,
    create_refresh_token,
    decode_token,
    get_current_user,
    verify_password,
)
from platform.models.user import User
from platform.schemas.auth import (
    AccessTokenResponse,
    LoginRequest,
    MeResponse,
    RefreshRequest,
    TokenResponse,
)

router = APIRouter(prefix="/auth")


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()

    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Account is disabled")

    user.last_login_at = datetime.now(UTC)
    await db.commit()

    return TokenResponse(
        access_token=create_access_token(
            user_id=str(user.id),
            email=user.email,
            role=user.role,
        ),
        refresh_token=create_refresh_token(user_id=str(user.id)),
    )


@router.post("/refresh", response_model=AccessTokenResponse)
async def refresh(payload: RefreshRequest, db: AsyncSession = Depends(get_db)):
    try:
        claims = decode_token(payload.refresh_token)
    except (TokenExpiredError, TokenInvalidError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired refresh token")

    if claims.get("type") != "refresh":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not a refresh token")

    result = await db.execute(select(User).where(User.id == claims["sub"]))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    return AccessTokenResponse(
        access_token=create_access_token(
            user_id=str(user.id),
            email=user.email,
            role=user.role,
        )
    )


@router.get("/me", response_model=MeResponse)
async def me(claims: dict = Depends(get_current_user)):
    return MeResponse(
        id=claims["sub"],
        email=claims["email"],
        role=claims["role"],
    )
```

- [ ] **Step 5: Register auth router in main.py**

In `platform/api/main.py`, add after the health router import:

```python
from platform.api.routes import health, auth   # add auth
```

And in `create_app()`, add after `app.include_router(health.router, ...)`:

```python
app.include_router(auth.router, tags=["auth"])
```

- [ ] **Step 6: Run tests — expect all pass**

```bash
pytest tests/integration/test_auth_endpoints.py -v
```

Expected:
```
PASSED tests/integration/test_auth_endpoints.py::test_login_success
PASSED tests/integration/test_auth_endpoints.py::test_login_wrong_password
PASSED tests/integration/test_auth_endpoints.py::test_login_unknown_email
PASSED tests/integration/test_auth_endpoints.py::test_refresh_token
PASSED tests/integration/test_auth_endpoints.py::test_protected_endpoint_without_token
PASSED tests/integration/test_auth_endpoints.py::test_protected_endpoint_with_valid_token
6 passed
```

- [ ] **Step 7: Commit**

```bash
git add platform/schemas/auth.py platform/api/routes/auth.py platform/api/main.py \
        tests/integration/test_auth_endpoints.py
git commit -m "feat: login, refresh, and /me endpoints with JWT + RBAC"
```

---

## Task 10: Full test suite run + smoke test

**Files:** none new

- [ ] **Step 1: Run the full test suite**

```bash
pytest --tb=short -q
```

Expected:
```
tests/unit/test_config.py ..                                           [  x%]
tests/unit/test_auth_core.py .....                                     [  x%]
tests/integration/test_health.py ..                                    [  x%]
tests/integration/test_auth_endpoints.py ......                        [  x%]
13 passed in x.xxs
```

If any test fails, fix it before proceeding.

- [ ] **Step 2: Smoke-test the running server**

Start the server:
```bash
uvicorn platform.api.main:app --reload --port 8000
```

In a second terminal:
```bash
curl -s http://localhost:8000/health | python3 -m json.tool
```

Expected:
```json
{
    "status": "ok",
    "version": "0.1.0",
    "environment": "development"
}
```

Test login:
```bash
curl -s -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@fleet.local","password":"admin"}' | python3 -m json.tool
```

Note: This returns 401 because no user exists yet. To create the first admin:

```bash
python3 -c "
import asyncio
from platform.db.session import AsyncSessionLocal
from platform.core.auth import hash_password
from platform.models.user import User
from datetime import UTC, datetime

async def seed():
    async with AsyncSessionLocal() as db:
        user = User(
            email='admin@fleet.local',
            password_hash=hash_password('changeme'),
            role='admin',
            first_seen_at=datetime.now(UTC),
        )
        db.add(user)
        await db.commit()
        print('Admin user created')

asyncio.run(seed())
"
```

Then login should return tokens:
```bash
curl -s -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@fleet.local","password":"changeme"}' | python3 -m json.tool
```

Expected:
```json
{
    "access_token": "eyJ...",
    "refresh_token": "eyJ...",
    "token_type": "bearer"
}
```

- [ ] **Step 3: Verify API docs are accessible in dev mode**

Open: `http://localhost:8000/docs`

Expected: FastAPI Swagger UI showing health + auth endpoints.

- [ ] **Step 4: Final commit**

```bash
git add .
git commit -m "chore: plan 1 complete — foundation working, all 13 tests passing"
```

---

## Plan 1 Self-Review

**Spec coverage check:**
- ✓ PostgreSQL 17 + TimescaleDB 2.x (latest-pg17 image)
- ✓ All 11 tables from RFC Section 9 created
- ✓ 3 hypertables (node_facts, drift_records, audit_events) with retention policies
- ✓ Continuous aggregate (fleet_drift_hourly) from RFC Section 9
- ✓ All indexes from RFC Section 9 created
- ✓ JWT HS256 auth from RFC Section 13
- ✓ RBAC via `require_role()` dependency from RFC Section 13
- ✓ bcrypt password hashing from RFC Section 13
- ✓ pydantic-settings config from RFC Section 7
- ✓ structlog JSON logging from RFC Section 15
- ✓ Docker Compose with health checks from RFC Section 15
- ✓ Test DB separate from main DB (fleet_test)

**Not in this plan (correct — belong in Plans 2–6):**
- Salt returner, grain ingest → Plan 2
- Node/group/drift API endpoints → Plan 3/4
- Celery workers → Plan 2
- React frontend → Plan 6
