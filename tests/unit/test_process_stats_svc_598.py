"""Unit coverage for the process-stats persistence service (#598).

CI runs only tests/unit/ under an 80% coverage gate on fleet_platform/services/,
so the service is covered here with a mocked AsyncSession (no live DB).
"""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from fleet_platform.schemas.ingest import ProcessStatItem
from fleet_platform.services.process_stats_svc import persist_process_stats


def _item(pid: int) -> ProcessStatItem:
    return ProcessStatItem(
        pid=pid,
        name="exo",
        cpu_pct=10.0,
        mem_rss_bytes=1024,
        mem_pct=1.0,
        num_threads=2,
    )


@pytest.fixture
def fake_node():
    return SimpleNamespace(id=uuid.uuid4())


async def test_persist_inserts_all_rows_and_commits(fake_node):
    db = MagicMock()
    db.add_all = MagicMock()
    db.commit = AsyncMock()

    items = [_item(1), _item(2), _item(3)]
    now = datetime.now(UTC)

    count = await persist_process_stats(db, fake_node, items, now)

    assert count == 3
    db.commit.assert_awaited_once()
    db.add_all.assert_called_once()
    added = db.add_all.call_args.args[0]
    assert len(added) == 3
    # Fields are mapped through from the schema onto the ORM rows.
    assert {r.pid for r in added} == {1, 2, 3}
    assert all(r.node_id == fake_node.id for r in added)
    assert all(r.collected_at == now for r in added)


async def test_persist_empty_list_commits_zero_rows(fake_node):
    db = MagicMock()
    db.add_all = MagicMock()
    db.commit = AsyncMock()

    count = await persist_process_stats(db, fake_node, [], datetime.now(UTC))

    assert count == 0
    db.commit.assert_awaited_once()
    assert len(db.add_all.call_args.args[0]) == 0
