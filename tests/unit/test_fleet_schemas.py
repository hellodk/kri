import uuid
from datetime import UTC, datetime

import pytest

from fleet_platform.schemas.fleet import FleetOverviewResponse, NodeListItem
from fleet_platform.schemas.group import GroupCreate
from fleet_platform.schemas.tag import TagCreate


def test_fleet_overview_response():
    r = FleetOverviewResponse(
        total_nodes=10,
        online=8,
        stale=1,
        offline=1,
        unknown=0,
        avg_drift_score=12,
        nodes_clean=6,
        nodes_low=2,
        nodes_medium=1,
        nodes_high=1,
        nodes_critical=0,
        last_updated=datetime.now(UTC),
    )
    assert r.total_nodes == 10
    assert r.online == 8


def test_node_list_item_has_required_fields():
    item = NodeListItem(
        id=uuid.uuid4(),
        minion_id="mac-01.local",
        hostname="mac-01",
        status="online",
        drift_score=5,
        last_seen_at=datetime.now(UTC),
        tags=[],
    )
    assert item.status == "online"


def test_group_create_requires_name_and_type():
    with pytest.raises(Exception):
        GroupCreate(type="static")  # missing name


def test_group_create_static():
    g = GroupCreate(name="prod-builders", type="static")
    assert g.predicate is None


def test_group_create_dynamic_requires_predicate():
    with pytest.raises(Exception):
        GroupCreate(name="prod", type="dynamic")  # missing predicate


def test_tag_create():
    t = TagCreate(key="env", value="prod")
    assert t.key == "env"
