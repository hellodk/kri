# tests/unit/test_group_resolver.py
import uuid
from unittest.mock import AsyncMock, MagicMock

from fleet_platform.services.group_resolver import resolve_dynamic_group, validate_predicate


def test_validate_predicate_valid():
    p = {"and": [{"key": "env", "value": "prod"}]}
    assert validate_predicate(p) is True


def test_validate_predicate_missing_and():
    assert validate_predicate({}) is False
    assert validate_predicate({"or": []}) is False


def test_validate_predicate_missing_key():
    assert validate_predicate({"and": [{"value": "prod"}]}) is False


def test_validate_predicate_missing_value():
    assert validate_predicate({"and": [{"key": "env"}]}) is False


def test_validate_predicate_empty_conditions():
    assert validate_predicate({"and": []}) is False


async def test_resolve_empty_predicate_returns_empty():
    mock_db = AsyncMock()
    result = await resolve_dynamic_group({}, mock_db)
    assert result == []


async def test_resolve_dynamic_group_with_valid_predicate():
    from fleet_platform.services.group_resolver import resolve_dynamic_group
    db = AsyncMock()
    node_id = uuid.uuid4()
    exec_result = MagicMock()
    exec_result.fetchall.return_value = [(node_id,)]
    db.execute.return_value = exec_result
    out = await resolve_dynamic_group({"and": [{"key": "env", "value": "prod"}]}, db)
    assert out == [node_id]
    db.execute.assert_called_once()


async def test_resolve_dynamic_group_multiple_conditions():
    from fleet_platform.services.group_resolver import resolve_dynamic_group
    db = AsyncMock()
    id1, id2 = uuid.uuid4(), uuid.uuid4()
    exec_result = MagicMock()
    exec_result.fetchall.return_value = [(id1,), (id2,)]
    db.execute.return_value = exec_result
    out = await resolve_dynamic_group(
        {"and": [{"key": "env", "value": "prod"}, {"key": "role", "value": "builder"}]}, db
    )
    assert len(out) == 2
    assert id1 in out and id2 in out


async def test_resolve_dynamic_group_no_matches():
    from fleet_platform.services.group_resolver import resolve_dynamic_group
    db = AsyncMock()
    exec_result = MagicMock()
    exec_result.fetchall.return_value = []
    db.execute.return_value = exec_result
    out = await resolve_dynamic_group({"and": [{"key": "env", "value": "staging"}]}, db)
    assert out == []
