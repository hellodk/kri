# Integration Tests

## Required environment

### PostgreSQL

| Variable | Example | Purpose |
|---|---|---|
| `TEST_DATABASE_URL` | `postgresql+psycopg://fleet:fleet@127.0.0.1:15432/fleet_test` | Test DB (tables created/dropped by fixtures) |
| `DATABASE_URL` | same as above | Picked up by `settings`; must match `TEST_DATABASE_URL` |

The PostgreSQL instance must have the following extensions available (the `test_engine` fixture creates them with `IF NOT EXISTS`):

- `pg_trgm` — required by the unified search API (`/api/v1/search`)
- `vector` — required by the RAG/embedding pipeline
- `timescaledb` — required by fleet health time-series tables

If `pg_trgm` is absent the search tests will fail with `UndefinedFunction: function similarity(...)`.

### Redis

| Variable | Example | Purpose |
|---|---|---|
| `REDIS_URL` | `redis://:redispass@127.0.0.1:16379/0` | Rate-limiter + token revocation; tests use an in-memory mock but Celery workers need a real URL |

The integration tests override the FastAPI dependency `get_redis` with an `AsyncMock`, so Redis
does not need to be reachable for most tests.  If Celery worker tasks are triggered (e.g.
`test_fleet_health_api.py::test_trigger_collect_returns_202`), the task is mocked via
`unittest.mock.patch` so Redis is still not required.

## Running the tests

```bash
source .venv/bin/activate
TEST_DATABASE_URL="postgresql+psycopg://fleet:fleet@127.0.0.1:15432/fleet_test" \
DATABASE_URL="postgresql+psycopg://fleet:fleet@127.0.0.1:15432/fleet_test" \
REDIS_URL="redis://:redispass@127.0.0.1:16379/0" \
python -m pytest tests/integration/ -q
```

Expected summary (green): `N passed, M skipped, K xfailed, 0 failed, 0 errors`.

## Known skips and xfails

| Test | Status | Reason |
|---|---|---|
| `test_rag_pipeline.py::test_bm25_retrieval_finds_inserted_chunk` | **SKIP** | `fleet_embeddings.tsv` generated column defined in migration `032_fleet_embeddings.py` but absent from the SQLAlchemy model; `create_all` cannot create it (REAL-BUG) |
| `test_alerts_api.py::test_create_webhook_validates_url_scheme` | **XFAIL** | REAL-BUG: `_validate_webhook_url` in `fleet_platform/services/alert_svc.py` allows `http://` (should reject non-https) |
| `test_groups_api.py::test_create_dynamic_group_missing_predicate_returns_422` | **XFAIL** | REAL-BUG: groups route raises `TypeError: Object of type ValueError is not JSON serializable` instead of a clean 422 |
| `test_search_api.py::test_search_by_hostname` | **XFAIL** | REAL-BUG: `coalesce(ip_address,'')` fails on INET column; fix is `coalesce(ip_address::text,'')` in `fleet_platform/api/routes/search.py` |
| `test_search_api.py::test_search_requires_min_3_chars` | **XFAIL** | Same REAL-BUG as above; also has a secondary TEST-BUG (expects 422 for 2-char query but route `min_length=2` allows it) |

## REAL-BUG tracker (file issues against these before closing the triage ticket)

1. **`fleet_platform/models/__init__.py`** — `AlertRule`, `WebhookConfig`, `AlertEvent` (from `alert.py`) and `SSHSession` (from `ssh_session.py`) are not imported.  `Base.metadata.create_all` therefore skips their tables, breaking any tests that hit those routes.  Workaround applied in `conftest.py` (explicit imports for test DB setup only).

2. **`fleet_platform/models/fleet_embedding.py`** — Missing `tsv tsvector GENERATED ALWAYS AS (to_tsvector('english', chunk_text)) STORED` column that migration `032_fleet_embeddings.py` adds.  The BM25 search service (`embedding_svc.py`) queries `WHERE tsv @@ plainto_tsquery(...)` which fails when the table is created via `create_all`.

3. **`fleet_platform/services/alert_svc.py`** — `_validate_webhook_url` checks `scheme not in ("http", "https")` instead of `scheme != "https"`, allowing insecure `http://` webhook targets.

4. **`fleet_platform/api/routes/groups.py`** — When a dynamic group is created without a `predicate`, the route raises a `ValueError` and includes the exception object (not `str(exc)`) in the 422 response body, causing `TypeError: Object of type ValueError is not JSON serializable`.

5. **`fleet_platform/api/routes/search.py`** — `_search_nodes` uses `coalesce(ip_address,'')` where `ip_address` is `INET` type.  PostgreSQL rejects the empty-string literal for INET.  Fix: `coalesce(ip_address::text,'')`.

6. **`playbooks/bootstrap_mac_mini.yml`** — YAML syntax error at line 297: `awk -F': '` inside an unquoted YAML scalar confuses PyYAML's scanner.  Fixed in this triage by converting the affected `shell:` tasks to block-scalar (`|`) style.
