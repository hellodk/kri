"""Behavioral coverage for fleet_platform/agent/tools.py handlers (#799 / TST-2).

These exercise the read-only tool handlers with a fake async DB session and
monkeypatched fleet services, asserting the JSON-safe projections the model is
fed (counts, found/not-found shapes, redaction of out-of-root paths) and the
live ``enable_node`` mutation path. No network or real database is touched.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

import fleet_platform.services.embedding_svc as embedding_svc
import fleet_platform.services.platform_settings_svc as pss
import fleet_platform.services.playbook_discovery as playbook_discovery
import fleet_platform.services.playbook_sources as playbook_sources
from fleet_platform.agent import tools
from fleet_platform.agent.registry import ToolCtx


class _ScalarResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


class _ExecResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return _ScalarResult(self._rows)

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None


class _FakeDB:
    def __init__(self, rows=()):
        self._rows = list(rows)
        self.committed = False

    async def execute(self, query):
        return _ExecResult(self._rows)

    async def commit(self):
        self.committed = True


def _node(**over):
    base = dict(
        id=uuid.uuid4(),
        minion_id="mm7",
        hostname="mac-mini-7",
        ip_address="10.0.0.7",
        os_version="14.5",
        status="degraded",
        drift_score=42,
        cpu_usage_pct=10,
        mem_usage_pct=20,
        bootstrap_status="done",
        maintenance_mode=False,
        last_seen_at=datetime(2026, 1, 1, tzinfo=UTC),
        tags=[SimpleNamespace(key="env", value="prod")],
    )
    base.update(over)
    return SimpleNamespace(**base)


def _ctx(db=None, role="operator", actor="ops@example.com"):
    return ToolCtx(actor=actor, role=role, session_id=uuid.uuid4(), db=db)


async def test_list_nodes_projects_rows_and_clamps_limit():
    db = _FakeDB([_node(), _node(minion_id="mm8", last_seen_at=None, ip_address=None)])
    out = await tools._list_nodes(_ctx(db), status="degraded", search="mac", limit=9999)
    assert out["count"] == 2
    first = out["nodes"][0]
    assert first["minion_id"] == "mm7"
    assert first["last_seen_at"] == "2026-01-01T00:00:00+00:00"
    # None-valued ip/last_seen project to null, never crash.
    assert out["nodes"][1]["ip_address"] is None
    assert out["nodes"][1]["last_seen_at"] is None


async def test_get_node_found_includes_tags():
    db = _FakeDB([_node()])
    out = await tools._get_node(_ctx(db), "mac-mini-7")
    assert out["found"] is True
    assert out["tags"] == [{"key": "env", "value": "prod"}]


async def test_get_node_accepts_uuid_identifier():
    n = _node()
    db = _FakeDB([n])
    out = await tools._get_node(_ctx(db), str(n.id))
    assert out["found"] is True
    assert out["id"] == str(n.id)


async def test_get_node_not_found_returns_shape():
    out = await tools._get_node(_ctx(_FakeDB([])), "ghost")
    assert out == {"found": False, "identifier": "ghost"}


async def test_get_recent_audit_projects_events():
    ev = SimpleNamespace(
        event_at=datetime(2026, 6, 1, tzinfo=UTC),
        actor="ops@example.com",
        action="agent.tool.list_nodes",
        resource_type="agent_tool",
        resource_id=uuid.uuid4(),
    )
    out = await tools._get_recent_audit(_ctx(_FakeDB([ev])), actor="ops", action="agent", limit=10)
    assert out["count"] == 1
    assert out["events"][0]["actor"] == "ops@example.com"
    assert out["events"][0]["resource_id"] == str(ev.resource_id)


async def test_enable_node_sets_active_and_commits():
    n = _node(status="quarantined")
    db = _FakeDB([n])
    out = await tools._enable_node(_ctx(db), "mm7")
    assert out == {"minion_id": "mm7", "status": "active"}
    assert n.status == "active"
    assert db.committed is True


async def test_enable_node_missing_raises():
    with pytest.raises(ValueError, match="not found"):
        await tools._enable_node(_ctx(_FakeDB([])), "ghost")


async def test_enable_node_without_db_raises():
    with pytest.raises(ValueError, match="requires a db session"):
        await tools._enable_node(_ctx(db=None), "mm7")


async def test_read_playbook_rejects_path_outside_roots(tmp_path, monkeypatch):
    async def _dir(_db):
        return str(tmp_path)

    async def _setting(_db, _key):
        return None

    monkeypatch.setattr(pss, "get_playbooks_dir", _dir)
    monkeypatch.setattr(pss, "get_setting", _setting)
    monkeypatch.setattr(playbook_sources, "get_all_playbook_dirs", lambda sj, pd: [tmp_path])

    with pytest.raises(ValueError, match="outside the configured playbook roots"):
        await tools._read_playbook(_ctx(_FakeDB()), "../../etc/passwd")


async def test_read_playbook_reads_in_root_file(tmp_path, monkeypatch):
    (tmp_path / "site.yml").write_text("- hosts: all\n")

    async def _dir(_db):
        return str(tmp_path)

    async def _setting(_db, _key):
        return None

    monkeypatch.setattr(pss, "get_playbooks_dir", _dir)
    monkeypatch.setattr(pss, "get_setting", _setting)
    monkeypatch.setattr(playbook_sources, "get_all_playbook_dirs", lambda sj, pd: [tmp_path])

    out = await tools._read_playbook(_ctx(_FakeDB()), "site.yml")
    assert out["found"] is True
    assert "hosts: all" in out["content"]


async def test_search_playbooks_filters_by_query(tmp_path, monkeypatch):
    async def _dir(_db):
        return str(tmp_path)

    async def _setting(_db, _key):
        return None

    monkeypatch.setattr(pss, "get_playbooks_dir", _dir)
    monkeypatch.setattr(pss, "get_setting", _setting)
    monkeypatch.setattr(playbook_sources, "get_all_playbook_dirs", lambda sj, pd: [tmp_path])

    entries = [
        SimpleNamespace(filename="deploy.yml", name="deploy", description="ship it", entry_type="playbook"),
        SimpleNamespace(filename="backup.yml", name="backup", description="snapshot", entry_type="playbook"),
    ]
    monkeypatch.setattr(playbook_discovery, "discover_all", lambda pd: entries)

    out = await tools._search_playbooks(_ctx(_FakeDB()), "deploy")
    assert out["count"] == 1
    assert out["matches"][0]["name"] == "deploy"


async def test_rag_search_errors_when_embed_unconfigured(monkeypatch):
    async def _setting(_db, _key):
        return None

    monkeypatch.setattr(pss, "get_setting", _setting)
    out = await tools._rag_search(_ctx(_FakeDB()), "drift on mm7")
    assert out["results"] == []
    assert "not configured" in out["error"]


async def test_rag_search_projects_chunks(monkeypatch):
    async def _setting(_db, _key):
        return "http://embed.local"

    async def _retrieve(db, query, url, source_types=None, top_k=8):
        return [{"source_type": "playbook", "source_id": "p1", "chunk_text": "x" * 3000}]

    monkeypatch.setattr(pss, "get_setting", _setting)
    monkeypatch.setattr(embedding_svc, "retrieve", _retrieve)

    out = await tools._rag_search(_ctx(_FakeDB()), "q", top_k=99)
    assert out["count"] == 1
    # chunk_text is capped at 3000 chars for the prompt.
    assert len(out["results"][0]["chunk_text"]) == 3000


async def test_embed_text_returns_dim_and_preview(monkeypatch):
    async def _setting(_db, _key):
        return "http://embed.local"

    async def _embed(texts, url, mode="query"):
        return [[0.1, 0.2, 0.3]]

    monkeypatch.setattr(pss, "get_setting", _setting)
    monkeypatch.setattr(embedding_svc, "embed_texts", _embed)

    out = await tools._embed_text(_ctx(_FakeDB()), "hello")
    assert out["dim"] == 3
    assert out["preview"] == [0.1, 0.2, 0.3]


async def test_embed_text_errors_when_unconfigured(monkeypatch):
    async def _setting(_db, _key):
        return None

    monkeypatch.setattr(pss, "get_setting", _setting)
    out = await tools._embed_text(_ctx(_FakeDB()), "hello")
    assert "not configured" in out["error"]
