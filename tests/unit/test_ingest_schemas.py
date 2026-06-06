# tests/unit/test_ingest_schemas.py
import pytest
from pydantic import ValidationError

from fleet_platform.schemas.ingest import ExecutionIngestPayload, GrainIngestPayload
from fleet_platform.schemas.node import NodeRegisterRequest, NodeRegisterResponse


def test_grain_payload_parses_minimal():
    p = GrainIngestPayload(
        minion_id="mac-mini-01.local",
        grains={"id": "mac-mini-01.local", "os": "MacOS"},
    )
    assert p.minion_id == "mac-mini-01.local"
    assert p.grains["os"] == "MacOS"


def test_grain_payload_requires_minion_id():
    with pytest.raises(ValidationError):
        GrainIngestPayload(grains={"id": "foo"})


def test_grain_payload_requires_grains():
    with pytest.raises(ValidationError):
        GrainIngestPayload(minion_id="mac-mini-01.local")


def test_execution_payload_parses():
    p = ExecutionIngestPayload(
        minion_id="mac-mini-01.local",
        jid="20260512100000123456",
        return_data={"test.ping": True},
        retcode=0,
        fun="test.ping",
        success=True,
    )
    assert p.retcode == 0
    assert p.success is True


def test_execution_payload_defaults():
    p = ExecutionIngestPayload(
        minion_id="mac-mini-01.local",
        jid="20260512100000123456",
        return_data={},
        fun="state.apply",
    )
    assert p.retcode == 0
    assert p.success is True


def test_node_register_request_requires_minion_id():
    with pytest.raises(ValidationError):
        NodeRegisterRequest(hostname="foo")


def test_node_register_response_has_token():
    import uuid

    r = NodeRegisterResponse(node_id=uuid.uuid4(), minion_id="foo.local", token="abc123")
    assert r.token == "abc123"
