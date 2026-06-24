"""Tests for the shared minion-id validator (#752 — ARC-8).

Run: pytest tests/unit/test_validators_752.py -q
"""

import pytest
from pydantic import ValidationError

from fleet_platform.core.validators import MINION_ID_RE, validate_minion_id
from fleet_platform.schemas.ansible import BootstrapRequest
from fleet_platform.schemas.fleet import NodeCreateRequest
from fleet_platform.schemas.ingest import (
    ExecutionIngestPayload,
    GrainIngestPayload,
    ProcessStatsIngestPayload,
)
from fleet_platform.schemas.node import NodeRegisterRequest
from fleet_platform.schemas.node_import import ImportRow

# ---------------------------------------------------------------------------
# Unit tests for the bare validator function
# ---------------------------------------------------------------------------

VALID_IDS = [
    "mac-mini-01.local",
    "node1",
    "a",
    "A-B_C.D",
    "x" * 128,
    "abc123",
    "salt.master-01",
]

INVALID_IDS = [
    "",
    "x" * 129,
    "has space",
    "has/slash",
    "has@at",
    "has$dollar",
    "has#hash",
    "has!bang",
]


@pytest.mark.parametrize("mid", VALID_IDS)
def test_validate_minion_id_accepts_valid(mid):
    assert validate_minion_id(mid) == mid


@pytest.mark.parametrize("mid", INVALID_IDS)
def test_validate_minion_id_rejects_invalid(mid):
    with pytest.raises(ValueError, match="minion_id must be"):
        validate_minion_id(mid)


def test_minion_id_re_no_length_escape():
    assert MINION_ID_RE.match("a")
    assert MINION_ID_RE.match("x" * 128)
    assert MINION_ID_RE.match("x" * 129) is None
    assert MINION_ID_RE.match("") is None


# ---------------------------------------------------------------------------
# Integration tests — validator wired into each input schema
# ---------------------------------------------------------------------------


class TestBootstrapRequest:
    def test_accepts_valid_minion_id(self):
        r = BootstrapRequest(minion_id="mac-mini-01.local", target_ip="10.0.0.1")
        assert r.minion_id == "mac-mini-01.local"

    def test_rejects_empty(self):
        with pytest.raises(ValidationError):
            BootstrapRequest(minion_id="", target_ip="10.0.0.1")

    def test_rejects_too_long(self):
        with pytest.raises(ValidationError):
            BootstrapRequest(minion_id="x" * 129, target_ip="10.0.0.1")

    def test_rejects_special_chars(self):
        with pytest.raises(ValidationError):
            BootstrapRequest(minion_id="bad id!", target_ip="10.0.0.1")


class TestNodeRegisterRequest:
    def test_accepts_valid(self):
        r = NodeRegisterRequest(minion_id="node-01")
        assert r.minion_id == "node-01"

    def test_rejects_invalid(self):
        with pytest.raises(ValidationError):
            NodeRegisterRequest(minion_id="node 01")


class TestNodeCreateRequest:
    def test_accepts_valid(self):
        r = NodeCreateRequest(minion_id="build-mac.corp")
        assert r.minion_id == "build-mac.corp"

    def test_rejects_too_long(self):
        with pytest.raises(ValidationError):
            NodeCreateRequest(minion_id="a" * 129)

    def test_rejects_slash(self):
        with pytest.raises(ValidationError):
            NodeCreateRequest(minion_id="foo/bar")


class TestGrainIngestPayload:
    def test_accepts_valid(self):
        p = GrainIngestPayload(minion_id="mac-01.local", grains={"os": "MacOS"})
        assert p.minion_id == "mac-01.local"

    def test_rejects_invalid(self):
        with pytest.raises(ValidationError):
            GrainIngestPayload(minion_id="has space", grains={})


class TestExecutionIngestPayload:
    def test_accepts_valid(self):
        p = ExecutionIngestPayload(
            minion_id="mac-01",
            jid="20260601",
            return_data={},
            fun="test.ping",
        )
        assert p.minion_id == "mac-01"

    def test_rejects_invalid(self):
        with pytest.raises(ValidationError):
            ExecutionIngestPayload(
                minion_id="bad@host",
                jid="x",
                return_data={},
                fun="test.ping",
            )


class TestProcessStatsIngestPayload:
    def test_accepts_valid(self):
        p = ProcessStatsIngestPayload(minion_id="mac-01", processes=[])
        assert p.minion_id == "mac-01"

    def test_rejects_empty(self):
        with pytest.raises(ValidationError):
            ProcessStatsIngestPayload(minion_id="", processes=[])


class TestImportRow:
    def test_accepts_valid(self):
        r = ImportRow(minion_id="build-01.corp")
        assert r.minion_id == "build-01.corp"

    def test_rejects_too_long(self):
        with pytest.raises(ValidationError):
            ImportRow(minion_id="b" * 129)

    def test_rejects_special_chars(self):
        with pytest.raises(ValidationError):
            ImportRow(minion_id="foo bar")
