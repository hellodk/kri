# tests/unit/test_llm_context_group_642.py
"""
#642 — node group column always showed "—" because the membership map was keyed by
GroupMember.node_id (a UUID) but looked up by str(row.minion_id) (a string).

Fix: Node.id is added to the node SELECT and the lookup uses str(row.id).

This test drives build_fleet_context with a fake async DB session that returns a node
and a matching group membership.  With the OLD code the assertion fails (group "—"
instead of "build"); with the fix it passes.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers — lightweight row stubs with attribute access
# ---------------------------------------------------------------------------

NODE_UUID = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")


def _scalar_result(value: Any) -> MagicMock:
    """Fake result whose .scalar_one() returns value."""
    r = MagicMock()
    r.scalar_one.return_value = value
    return r


def _scalars_result(values: list) -> MagicMock:
    """Fake result whose .scalars().all() returns values."""
    r = MagicMock()
    r.scalars.return_value.all.return_value = values
    return r


def _rows_result(rows: list) -> MagicMock:
    """Fake result whose .all() returns rows."""
    r = MagicMock()
    r.all.return_value = rows
    return r


def _node_row():
    """Row returned by the node SELECT (now includes .id)."""
    return SimpleNamespace(
        id=NODE_UUID,
        hostname="mac-mini-1",
        minion_id="mm1",
        ip_address="192.168.1.10",
        status="online",
        last_seen_at=None,
    )


def _membership_row():
    """Row returned by the membership SELECT — node_id matches NODE_UUID."""
    return SimpleNamespace(node_id=NODE_UUID, name="build")


# ---------------------------------------------------------------------------
# Fake async session
# ---------------------------------------------------------------------------


class _FakeSession:
    """
    Dispatches execute() calls by position.  build_fleet_context makes exactly
    five execute() calls in order:
      1. node_count  → scalar_one()
      2. online_count → scalar_one()
      3. groups       → scalars().all()
      4. node SELECT  → .all()
      5. membership   → .all()
    """

    def __init__(self) -> None:
        self._results = iter(
            [
                _scalar_result(1),  # node_count
                _scalar_result(1),  # online_count
                _scalars_result(["build"]),  # groups
                _rows_result([_node_row()]),  # node rows
                _rows_result([_membership_row()]),  # membership rows
            ]
        )

    async def execute(self, stmt):  # noqa: ARG002
        return next(self._results)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_group_resolved_correctly_for_node():
    """
    When node.id matches GroupMember.node_id the group must appear in the
    context table — not "—".  This is the regression test for #642.
    """
    fake_db = _FakeSession()

    # Patch get_settings_bulk (imported inside build_fleet_context) to return {}
    # so include_ips defaults to true and embed_url is empty (RAG skipped).
    with patch(
        "fleet_platform.services.platform_settings_svc.get_settings_bulk",
        new=AsyncMock(return_value={}),
    ):
        # Also patch _redact_sensitive_data to be a no-op so we can inspect raw output.
        with patch(
            "fleet_platform.services.llm_svc._redact_sensitive_data",
            side_effect=lambda text, **_kw: text,
        ):
            from fleet_platform.services.llm_context import build_fleet_context

            # #883: build_fleet_context now returns (system_prompt, citations).
            result, _ = await build_fleet_context(fake_db, "fleet_query", query="x")

    # The group "build" must appear in the node row — NOT the dash placeholder.
    assert "| build |" in result, f"Expected '| build |' in context table but got:\n{result}"
    # Sanity: node hostname present
    assert "mac-mini-1" in result


@pytest.mark.asyncio
async def test_group_dash_when_no_membership():
    """
    When there is no membership entry the group column must show "—" (dash).
    This verifies the default fallback still works after the fix.
    """

    class _NoMemberSession:
        def __init__(self) -> None:
            self._results = iter(
                [
                    _scalar_result(1),
                    _scalar_result(1),
                    _scalars_result(["build"]),
                    _rows_result([_node_row()]),
                    _rows_result([]),  # no membership rows
                ]
            )

        async def execute(self, stmt):  # noqa: ARG002
            return next(self._results)

    fake_db = _NoMemberSession()

    with patch(
        "fleet_platform.services.platform_settings_svc.get_settings_bulk",
        new=AsyncMock(return_value={}),
    ):
        with patch(
            "fleet_platform.services.llm_svc._redact_sensitive_data",
            side_effect=lambda text, **_kw: text,
        ):
            from fleet_platform.services.llm_context import build_fleet_context

            # #883: build_fleet_context now returns (system_prompt, citations).
            result, _ = await build_fleet_context(fake_db, "fleet_query", query="x")

    # Without membership the dash must appear for the group column
    assert "| — |" in result or "| \\— |" in result or result.count("—") >= 1
    assert "mac-mini-1" in result
