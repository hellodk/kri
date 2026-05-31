# tests/unit/test_llm_context.py
from unittest.mock import AsyncMock, MagicMock

import pytest


def test_build_context_returns_nonempty_string():
    from fleet_platform.services.llm_context import build_static_context
    ctx = build_static_context(
        node_count=5,
        online_count=4,
        groups=["dev", "prod"],
        salt_master="salt.fleet.local",
        playbooks_dir="/srv/playbooks",
    )
    assert isinstance(ctx, str)
    assert len(ctx) > 50


def test_build_context_contains_node_count():
    from fleet_platform.services.llm_context import build_static_context
    ctx = build_static_context(
        node_count=12,
        online_count=10,
        groups=[],
        salt_master="salt.local",
        playbooks_dir="/srv",
    )
    assert "12" in ctx
    assert "10" in ctx


def test_build_context_contains_groups():
    from fleet_platform.services.llm_context import build_static_context
    ctx = build_static_context(
        node_count=3,
        online_count=3,
        groups=["alpha", "beta", "gamma"],
        salt_master="s",
        playbooks_dir="/p",
    )
    assert "alpha" in ctx
    assert "beta" in ctx
    assert "gamma" in ctx


def test_intent_addendum_covers_all_intents():
    from fleet_platform.services.llm_context import INTENT_ADDENDUM
    assert set(INTENT_ADDENDUM.keys()) == {"salt_state", "ansible_playbook", "fleet_command", "explain", "fleet_query"}


def test_build_static_context_unknown_intent_falls_back_to_empty():
    from fleet_platform.services.llm_context import INTENT_ADDENDUM
    result = INTENT_ADDENDUM.get("magic_wand", "")
    assert result == ""


@pytest.mark.asyncio
async def test_build_fleet_context_assembles_prompt():
    """build_fleet_context fetches DB counts/groups/settings and builds the prompt."""
    from unittest.mock import patch

    import fleet_platform.services.platform_settings_svc as svc_mod
    from fleet_platform.services.llm_context import build_fleet_context

    mock_db = AsyncMock()

    node_count_result = MagicMock()
    node_count_result.scalar_one.return_value = 7

    online_count_result = MagicMock()
    online_count_result.scalar_one.return_value = 5

    groups_result = MagicMock()
    groups_result.scalars.return_value.all.return_value = ["dev", "prod"]

    nodes_result = MagicMock()
    nodes_result.all.return_value = []

    membership_result = MagicMock()
    membership_result.all.return_value = []

    mock_db.execute = AsyncMock(side_effect=[
        node_count_result, online_count_result, groups_result, nodes_result, membership_result,
    ])

    async def fake_get_setting(db, key):
        return {"salt_master_address": "salt.local", "ansible_endpoint_url": "/srv/plays"}.get(key)

    with patch.object(svc_mod, "get_setting", side_effect=fake_get_setting):
        ctx = await build_fleet_context(mock_db, "salt_state")

    assert "7" in ctx
    assert "5" in ctx
    assert "SaltStack" in ctx


@pytest.mark.asyncio
async def test_build_fleet_context_appends_intent_addendum():
    from unittest.mock import patch

    from fleet_platform.services.llm_context import INTENT_ADDENDUM, build_fleet_context

    mock_db = AsyncMock()

    count_result = MagicMock()
    count_result.scalar_one.side_effect = [3, 3]
    groups_result = MagicMock()
    groups_result.scalars.return_value.all.return_value = []

    import fleet_platform.services.platform_settings_svc as svc_mod

    async def fake_get_setting(db, key):
        return None

    nodes_result2 = MagicMock()
    nodes_result2.all.return_value = []

    membership_result2 = MagicMock()
    membership_result2.all.return_value = []

    with patch.object(svc_mod, "get_setting", side_effect=fake_get_setting):
        mock_db.execute = AsyncMock(side_effect=[
            count_result, count_result, groups_result, nodes_result2, membership_result2,
        ])
        ctx = await build_fleet_context(mock_db, "ansible_playbook")

    assert INTENT_ADDENDUM["ansible_playbook"] in ctx
