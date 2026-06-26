"""Tests for #306 (prompt injection) and #307 (bulk settings)."""

from fleet_platform.services.llm_context import _sanitize_cell, build_static_context


def test_sanitize_cell_escapes_pipe():
    result = _sanitize_cell("host | inject")
    # Pipes should be escaped, not removed
    assert "\\|" in result
    # The text around the pipe should be preserved
    assert "host" in result and "inject" in result


def test_sanitize_cell_strips_newlines():
    assert "\n" not in _sanitize_cell("host\n## Rules")
    assert "\r" not in _sanitize_cell("host\rinjection")


def test_node_hostname_injection_does_not_break_table():
    """Malicious hostname must not add extra Markdown table columns."""
    records = [
        {
            "hostname": "mm1 | bad | data | extra",
            "minion_id": "mm1",
            "ip": "10.0.0.1",
            "status": "online",
            "last_seen": "1m ago",
            "group": "prod",
        }
    ]
    ctx = build_static_context(
        node_count=1,
        online_count=1,
        groups=["prod"],
        salt_master="s",
        playbooks_dir="/p",
        node_records=records,
    )
    # The hostname injection attempt should be escaped, preventing table breakage
    assert "mm1 \\|" in ctx, "Pipes in hostname must be escaped"
    # The escaped pipes should appear in the table, not create extra columns
    assert "mm1 \\| bad \\| data \\| extra" in ctx


def test_build_fleet_context_uses_bulk_settings():
    """build_fleet_context must call get_settings_bulk rather than individual get_setting calls.

    Both helpers are imported locally inside build_fleet_context, so we patch them at their
    source module (platform_settings_svc) where the late import resolves them.
    """
    import asyncio
    from unittest.mock import AsyncMock, MagicMock, patch

    from fleet_platform.services.llm_context import build_fleet_context

    async def _run():
        # `await db.execute(...)` must return a *sync* result object whose
        # .scalars()/.scalar_one()/.all() are plain (non-coroutine) calls.
        result = MagicMock()
        result.scalar_one.return_value = 0
        result.scalars.return_value.all.return_value = []
        result.all.return_value = []

        db = AsyncMock()
        db.execute = AsyncMock(return_value=result)

        with (
            patch(
                "fleet_platform.services.platform_settings_svc.get_settings_bulk",
                new_callable=AsyncMock,
            ) as mock_bulk,
            patch(
                "fleet_platform.services.platform_settings_svc.get_setting",
                new_callable=AsyncMock,
            ) as mock_single,
        ):
            mock_bulk.return_value = {}
            await build_fleet_context(db=db, intent="test")

        assert mock_bulk.called, "build_fleet_context must call get_settings_bulk for settings"
        assert not mock_single.called, (
            "build_fleet_context must not call individual get_setting() — use get_settings_bulk"
        )

    asyncio.run(_run())
