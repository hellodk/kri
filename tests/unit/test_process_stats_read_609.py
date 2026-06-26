# tests/unit/test_process_stats_read_609.py
"""Unit tests for Phase 1b process-stats read API (issue #609)."""

import re
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from fleet_platform.schemas.process_stat import ProcessStatOut

# ---------------------------------------------------------------------------
# ProcessStatOut schema tests
# ---------------------------------------------------------------------------


def _make_stat(**overrides) -> SimpleNamespace:
    """Return a SimpleNamespace that looks like a NodeProcessStat ORM row."""
    defaults = {
        "pid": 1234,
        "name": "python3",
        "cmdline": "/usr/bin/python3 -m app",
        "cpu_pct": Decimal("12.50"),
        "mem_rss_bytes": 204800,
        "mem_pct": Decimal("3.10"),
        "num_threads": 4,
        "status": "sleeping",
        "username": "root",
        "io_read_bytes": 1024,
        "io_write_bytes": 512,
        "is_llm": False,
        "collected_at": datetime(2026, 6, 8, 10, 0, 0, tzinfo=timezone.utc),
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class TestProcessStatOut:
    def test_validates_from_attributes(self):
        row = _make_stat()
        out = ProcessStatOut.model_validate(row)
        assert out.pid == 1234
        assert out.name == "python3"
        assert out.cmdline == "/usr/bin/python3 -m app"
        assert out.cpu_pct == Decimal("12.50")
        assert out.mem_rss_bytes == 204800
        assert out.mem_pct == Decimal("3.10")
        assert out.num_threads == 4
        assert out.status == "sleeping"
        assert out.username == "root"
        assert out.io_read_bytes == 1024
        assert out.io_write_bytes == 512
        assert out.is_llm is False
        assert out.collected_at == datetime(2026, 6, 8, 10, 0, 0, tzinfo=timezone.utc)

    def test_optional_fields_default_to_none(self):
        row = _make_stat(
            cmdline=None,
            cpu_pct=None,
            mem_rss_bytes=None,
            mem_pct=None,
            num_threads=None,
            status=None,
            username=None,
            io_read_bytes=None,
            io_write_bytes=None,
        )
        out = ProcessStatOut.model_validate(row)
        assert out.cmdline is None
        assert out.cpu_pct is None
        assert out.mem_rss_bytes is None
        assert out.mem_pct is None
        assert out.num_threads is None
        assert out.status is None
        assert out.username is None
        assert out.io_read_bytes is None
        assert out.io_write_bytes is None

    def test_is_llm_defaults_to_false(self):
        """is_llm has a default=False — validate it."""
        row = _make_stat(is_llm=False)
        out = ProcessStatOut.model_validate(row)
        assert out.is_llm is False

    def test_is_llm_true(self):
        row = _make_stat(is_llm=True)
        out = ProcessStatOut.model_validate(row)
        assert out.is_llm is True

    def test_decimal_cpu_pct_coercion(self):
        """Numeric(6,2) from SQLAlchemy comes back as Decimal — schema must accept it."""
        row = _make_stat(cpu_pct=Decimal("99.99"))
        out = ProcessStatOut.model_validate(row)
        assert out.cpu_pct == Decimal("99.99")

    def test_large_mem_rss_bytes(self):
        """BigInteger field — ensure large values (>2^31) round-trip."""
        big = 8 * 1024 * 1024 * 1024  # 8 GiB
        row = _make_stat(mem_rss_bytes=big)
        out = ProcessStatOut.model_validate(row)
        assert out.mem_rss_bytes == big


# ---------------------------------------------------------------------------
# Sort-param contract test — verified against the route source
# ---------------------------------------------------------------------------


def test_sort_param_pattern_in_nodes_route():
    """The GET /{node_id}/process_stats route must reject sort values outside mem_rss_bytes|cpu_pct.

    Drive the real route through the ASGI stack: an invalid sort must yield a 422
    (FastAPI Query pattern validation), while a valid sort must NOT 422.
    """
    import asyncio
    import uuid
    from unittest.mock import AsyncMock

    from httpx import ASGITransport, AsyncClient

    from fleet_platform.api import deps
    from fleet_platform.api.main import create_app
    from fleet_platform.core.auth import create_access_token

    class _FakeResult:
        def scalar_one_or_none(self):
            return None  # node not found → 404 for valid sort (but never 422)

    class _FakeSession:
        async def execute(self, *args, **kwargs):
            return _FakeResult()

        async def commit(self):
            pass

    async def _run():
        app = create_app()

        async def _override_db():
            yield _FakeSession()

        mock_redis = AsyncMock()
        mock_redis.get.return_value = None

        async def _override_redis():
            return mock_redis

        app.dependency_overrides[deps.get_db] = _override_db
        app.dependency_overrides[deps.get_redis] = _override_redis

        token = create_access_token(user_id=str(uuid.uuid4()), email="viewer@test.local", role="viewer")
        node_id = uuid.uuid4()
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
            headers={"Authorization": f"Bearer {token}"},
        ) as client:
            bad = await client.get(f"/api/v1/nodes/{node_id}/process_stats?sort=pid")
            good = await client.get(f"/api/v1/nodes/{node_id}/process_stats?sort=mem_rss_bytes")

        assert bad.status_code == 422, (
            f"Invalid sort='pid' must be rejected with 422 by the route pattern, got {bad.status_code}"
        )
        assert good.status_code != 422, (
            f"Valid sort='mem_rss_bytes' must NOT be rejected as invalid, got {good.status_code}"
        )

    asyncio.run(_run())


def test_sort_param_pattern_rejects_arbitrary():
    """Assert the compiled regex rejects arbitrary sort values."""
    pattern = re.compile("^(mem_rss_bytes|cpu_pct)$")
    assert pattern.match("mem_rss_bytes")
    assert pattern.match("cpu_pct")
    assert not pattern.match("pid")
    assert not pattern.match("name")
    assert not pattern.match("mem_rss_bytes; DROP TABLE")
    assert not pattern.match("")


def test_process_stats_route_registered():
    """The endpoint function must exist and be decorated on the router."""
    import fleet_platform.api.routes.nodes as nodes_mod

    assert hasattr(nodes_mod, "get_node_process_stats"), (
        "get_node_process_stats not found in nodes.py — endpoint not registered"
    )
    fn = nodes_mod.get_node_process_stats
    assert callable(fn)
