from types import SimpleNamespace

from sqlalchemy.sql.selectable import Select


class _ScalarResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


class _ExecuteResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return _ScalarResult(self._rows)

    def all(self):
        return list(self._rows)


class _FakeSession:
    def __init__(self, nodes):
        self.nodes = nodes
        self.node_limits = []
        self.expunge_calls = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def execute(self, statement):
        from fleet_platform.models.node import Node

        if _selects_entity(statement, Node):
            limit_clause = statement._limit_clause
            assert limit_clause is not None, "node reindex must select nodes with a LIMIT (#744)"
            limit = int(limit_clause.value)
            offset_clause = statement._offset_clause
            offset = int(offset_clause.value) if offset_clause is not None else 0
            self.node_limits.append(limit)
            return _ExecuteResult(self.nodes[offset : offset + limit])

        return _ExecuteResult(
            [
                SimpleNamespace(node_id=self.nodes[0].id, name="edge"),
                SimpleNamespace(node_id=self.nodes[2].id, name="core"),
            ]
        )

    def expunge_all(self):
        self.expunge_calls += 1


def _selects_entity(statement, entity) -> bool:
    return isinstance(statement, Select) and any(
        description.get("entity") is entity for description in statement.column_descriptions
    )


def test_reindex_nodes_processes_nodes_in_bounded_batches(monkeypatch):
    """#744: reindex_nodes must not materialize the full nodes table at once."""
    from fleet_platform.db import session as session_module
    from fleet_platform.models.node import Node
    from fleet_platform.services import embedding_svc, platform_settings_svc
    from fleet_platform.workers import embedding_tasks

    nodes = [
        Node(id=f"node-{idx}", hostname=f"host-{idx}", ip_address=f"10.0.0.{idx}", status="online") for idx in range(7)
    ]
    fake_session = _FakeSession(nodes)
    chunked_ids = []
    upserted_batches = []
    swept_ids = []

    def fake_session_factory():
        return fake_session

    async def fake_get_settings_bulk(db, keys):
        return {
            platform_settings_svc.LLM_EMBED_BASE_URL: "http://embed.local",
            platform_settings_svc.LLM_INCLUDE_NODE_IPS: "true",
        }

    def fake_chunk_node(**kwargs):
        chunked_ids.append(kwargs["node_id"])
        return [{"source_type": "node", "source_id": kwargs["node_id"], "chunk_text": kwargs["hostname"]}]

    async def fake_upsert_chunks(db, chunks, embed_url):
        upserted_batches.append([chunk["source_id"] for chunk in chunks])
        return len(chunks)

    async def fake_sweep_deleted_sources(db, source_type, source_ids):
        swept_ids.extend(source_ids)
        return 0

    monkeypatch.setattr(session_module, "AsyncSessionLocal", fake_session_factory)
    monkeypatch.setattr(platform_settings_svc, "get_settings_bulk", fake_get_settings_bulk)
    monkeypatch.setattr(embedding_svc, "chunk_node", fake_chunk_node)
    monkeypatch.setattr(embedding_svc, "upsert_chunks", fake_upsert_chunks)
    monkeypatch.setattr(embedding_svc, "sweep_deleted_sources", fake_sweep_deleted_sources)
    monkeypatch.setattr(embedding_tasks, "NODE_REINDEX_BATCH_SIZE", 3, raising=False)

    result = embedding_tasks.reindex_nodes.run()

    assert result == {"upserted": 7, "total": 7, "swept": 0}
    assert chunked_ids == [str(node.id) for node in nodes]
    assert swept_ids == [str(node.id) for node in nodes]
    assert upserted_batches == [
        ["node-0", "node-1", "node-2"],
        ["node-3", "node-4", "node-5"],
        ["node-6"],
    ]
    assert fake_session.node_limits == [3, 3, 3]
    assert fake_session.expunge_calls == 3
