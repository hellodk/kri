# tests/unit/test_ios_tracking_svc.py
import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from fleet_platform.services.ios_tracking_svc import (
    check_jenkins_agent,
    get_expiring_certs,
    update_node_from_grains,
)

# ---------------------------------------------------------------------------
# update_node_from_grains
# ---------------------------------------------------------------------------


async def test_update_node_from_grains_node_not_found():
    db = AsyncMock()
    exec_result = MagicMock()
    exec_result.scalar_one_or_none.return_value = None
    db.execute.return_value = exec_result

    node_id = uuid.uuid4()
    await update_node_from_grains(node_id, {"osrelease": "14.4"}, db)

    # DB was queried but nothing was mutated — add/commit never called
    db.add.assert_not_called()
    db.commit.assert_not_called()


async def test_update_node_from_grains_sets_macos_version():
    db = AsyncMock()
    node = MagicMock()
    exec_result = MagicMock()
    exec_result.scalar_one_or_none.return_value = node
    db.execute.return_value = exec_result

    node_id = uuid.uuid4()
    await update_node_from_grains(node_id, {"osrelease": "14.4"}, db)

    assert node.macos_version == "14.4"


async def test_update_node_from_grains_sets_xcode_from_grain():
    db = AsyncMock()
    node = MagicMock()
    exec_result = MagicMock()
    exec_result.scalar_one_or_none.return_value = node
    db.execute.return_value = exec_result

    node_id = uuid.uuid4()
    await update_node_from_grains(node_id, {"xcode_version": "15.2"}, db)

    assert node.xcode_version == "15.2"


async def test_update_node_from_grains_sets_xcode_from_brew():
    db = AsyncMock()
    node = MagicMock()
    exec_result = MagicMock()
    exec_result.scalar_one_or_none.return_value = node
    db.execute.return_value = exec_result

    node_id = uuid.uuid4()
    await update_node_from_grains(node_id, {"brew_pkgs": {"xcode-select": "15.1"}}, db)

    assert node.xcode_version == "15.1"


async def test_update_node_from_grains_no_xcode_keys():
    db = AsyncMock()
    node = MagicMock(spec=[])  # no pre-set attributes
    exec_result = MagicMock()
    exec_result.scalar_one_or_none.return_value = node
    db.execute.return_value = exec_result

    node_id = uuid.uuid4()
    await update_node_from_grains(node_id, {}, db)

    assert not hasattr(node, "xcode_version")


# ---------------------------------------------------------------------------
# check_jenkins_agent
# ---------------------------------------------------------------------------


async def test_check_jenkins_agent_not_found():
    db = AsyncMock()
    exec_result = MagicMock()
    exec_result.scalar_one_or_none.return_value = None
    db.execute.return_value = exec_result

    with patch("urllib.request.urlopen") as mock_urlopen:
        await check_jenkins_agent(uuid.uuid4(), db)
        mock_urlopen.assert_not_called()

    db.commit.assert_not_called()


async def test_check_jenkins_agent_online():
    db = AsyncMock()
    agent = MagicMock()
    agent.jenkins_url = "https://jenkins.example.com"
    agent.agent_name = "mac-agent-01"
    exec_result = MagicMock()
    exec_result.scalar_one_or_none.return_value = agent
    db.execute.return_value = exec_result

    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps({"offline": False}).encode()
    mock_urlopen = MagicMock()
    mock_urlopen.__enter__ = lambda s: mock_resp
    mock_urlopen.__exit__ = MagicMock(return_value=False)

    with patch("urllib.request.urlopen", return_value=mock_urlopen):
        await check_jenkins_agent(uuid.uuid4(), db)

    assert agent.status == "online"
    db.commit.assert_called_once()


async def test_check_jenkins_agent_offline():
    db = AsyncMock()
    agent = MagicMock()
    agent.jenkins_url = "https://jenkins.example.com"
    agent.agent_name = "mac-agent-02"
    exec_result = MagicMock()
    exec_result.scalar_one_or_none.return_value = agent
    db.execute.return_value = exec_result

    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps({"offline": True}).encode()
    mock_urlopen = MagicMock()
    mock_urlopen.__enter__ = lambda s: mock_resp
    mock_urlopen.__exit__ = MagicMock(return_value=False)

    with patch("urllib.request.urlopen", return_value=mock_urlopen):
        await check_jenkins_agent(uuid.uuid4(), db)

    assert agent.status == "offline"
    db.commit.assert_called_once()


async def test_check_jenkins_agent_network_error():
    db = AsyncMock()
    agent = MagicMock()
    agent.jenkins_url = "https://jenkins.example.com"
    agent.agent_name = "mac-agent-03"
    exec_result = MagicMock()
    exec_result.scalar_one_or_none.return_value = agent
    db.execute.return_value = exec_result

    with patch("urllib.request.urlopen", side_effect=Exception("connection refused")):
        await check_jenkins_agent(uuid.uuid4(), db)

    assert agent.status == "unknown"
    db.commit.assert_called_once()


# ---------------------------------------------------------------------------
# get_expiring_certs
# ---------------------------------------------------------------------------


async def test_get_expiring_certs_default_30_days():
    db = AsyncMock()
    cert1 = MagicMock()
    cert2 = MagicMock()
    exec_result = MagicMock()
    exec_result.scalars.return_value.all.return_value = [cert1, cert2]
    db.execute.return_value = exec_result

    result = await get_expiring_certs(db)

    assert result == [cert1, cert2]
    db.execute.assert_called_once()


async def test_get_expiring_certs_custom_days():
    db = AsyncMock()
    cert1 = MagicMock()
    exec_result = MagicMock()
    exec_result.scalars.return_value.all.return_value = [cert1]
    db.execute.return_value = exec_result

    result = await get_expiring_certs(db, days=7)

    assert len(result) == 1
    db.execute.assert_called_once()
