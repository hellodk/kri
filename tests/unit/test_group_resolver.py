# tests/unit/test_group_resolver.py
from unittest.mock import AsyncMock

import pytest

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
