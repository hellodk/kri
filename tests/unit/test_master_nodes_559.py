"""Tests for frontend/src/lib/masterNodes.ts — issue #559, epic master-lifecycle.

Tests the pure helper functions:
- mastersByNodeId(masters) → Set<string>
- isMasterNode(nodeId, masters) → boolean
- masterHealthSummary(masters) → {healthy, degraded, unreachable, unknown, total}

Runs the real TypeScript via node --experimental-strip-types.
No mocks — tests the actual implementation.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent.parent
HARNESS = Path(__file__).parent / "_master_nodes_559_harness.ts"
HELPER = ROOT / "frontend/src/lib/masterNodes.ts"


def _run_harness(cases: list[dict]) -> list[dict]:
    if shutil.which("node") is None:
        pytest.skip("node not available")
    if not HELPER.exists():
        pytest.fail(f"{HELPER} does not exist — create frontend/src/lib/masterNodes.ts")
    proc = subprocess.run(
        [
            "node",
            "--experimental-strip-types",
            "--no-warnings",
            str(HARNESS),
            json.dumps(cases),
        ],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
        timeout=30,
    )
    if proc.returncode != 0:
        pytest.fail(f"harness failed (rc={proc.returncode}):\n{proc.stderr}\n{proc.stdout}")
    return json.loads(proc.stdout)


# ── mastersByNodeId ──────────────────────────────────────────────────────────


class TestMastersByNodeId:
    def test_empty_list_returns_empty_set(self):
        results = _run_harness([{"fn": "mastersByNodeId", "masters": []}])
        assert results[0]["result"] == []

    def test_single_master_with_node_id(self):
        results = _run_harness(
            [
                {
                    "fn": "mastersByNodeId",
                    "masters": [{"node_id": "abc-123", "status": "healthy"}],
                }
            ]
        )
        assert results[0]["result"] == ["abc-123"]

    def test_null_node_id_excluded(self):
        results = _run_harness(
            [
                {
                    "fn": "mastersByNodeId",
                    "masters": [
                        {"node_id": None, "status": "healthy"},
                        {"node_id": "node-1", "status": "degraded"},
                    ],
                }
            ]
        )
        assert results[0]["result"] == ["node-1"]

    def test_multiple_masters_all_with_node_id(self):
        results = _run_harness(
            [
                {
                    "fn": "mastersByNodeId",
                    "masters": [
                        {"node_id": "node-a", "status": "healthy"},
                        {"node_id": "node-b", "status": "unreachable"},
                        {"node_id": "node-c", "status": "unknown"},
                    ],
                }
            ]
        )
        assert set(results[0]["result"]) == {"node-a", "node-b", "node-c"}

    def test_all_null_node_ids_returns_empty(self):
        results = _run_harness(
            [
                {
                    "fn": "mastersByNodeId",
                    "masters": [
                        {"node_id": None, "status": "healthy"},
                        {"node_id": None, "status": "degraded"},
                    ],
                }
            ]
        )
        assert results[0]["result"] == []


# ── isMasterNode ─────────────────────────────────────────────────────────────


class TestIsMasterNode:
    def test_node_is_master(self):
        results = _run_harness(
            [
                {
                    "fn": "isMasterNode",
                    "nodeId": "node-1",
                    "masters": [{"node_id": "node-1", "status": "healthy"}],
                }
            ]
        )
        assert results[0]["result"] is True

    def test_node_is_not_master(self):
        results = _run_harness(
            [
                {
                    "fn": "isMasterNode",
                    "nodeId": "node-2",
                    "masters": [{"node_id": "node-1", "status": "healthy"}],
                }
            ]
        )
        assert results[0]["result"] is False

    def test_empty_masters_returns_false(self):
        results = _run_harness(
            [
                {
                    "fn": "isMasterNode",
                    "nodeId": "node-1",
                    "masters": [],
                }
            ]
        )
        assert results[0]["result"] is False

    def test_null_node_id_master_does_not_match(self):
        results = _run_harness(
            [
                {
                    "fn": "isMasterNode",
                    "nodeId": "node-1",
                    "masters": [{"node_id": None, "status": "healthy"}],
                }
            ]
        )
        assert results[0]["result"] is False

    def test_multiple_masters_correct_match(self):
        results = _run_harness(
            [
                {
                    "fn": "isMasterNode",
                    "nodeId": "node-b",
                    "masters": [
                        {"node_id": "node-a", "status": "healthy"},
                        {"node_id": "node-b", "status": "degraded"},
                        {"node_id": None, "status": "unknown"},
                    ],
                }
            ]
        )
        assert results[0]["result"] is True


# ── masterHealthSummary ──────────────────────────────────────────────────────


class TestMasterHealthSummary:
    def test_empty_returns_zeros(self):
        results = _run_harness([{"fn": "masterHealthSummary", "masters": []}])
        r = results[0]["result"]
        assert r == {"healthy": 0, "degraded": 0, "unreachable": 0, "unknown": 0, "total": 0}

    def test_all_healthy(self):
        results = _run_harness(
            [
                {
                    "fn": "masterHealthSummary",
                    "masters": [
                        {"node_id": None, "status": "healthy"},
                        {"node_id": None, "status": "healthy"},
                    ],
                }
            ]
        )
        r = results[0]["result"]
        assert r["healthy"] == 2
        assert r["total"] == 2
        assert r["degraded"] == 0
        assert r["unreachable"] == 0
        assert r["unknown"] == 0

    def test_mixed_statuses(self):
        results = _run_harness(
            [
                {
                    "fn": "masterHealthSummary",
                    "masters": [
                        {"node_id": None, "status": "healthy"},
                        {"node_id": None, "status": "degraded"},
                        {"node_id": None, "status": "unreachable"},
                        {"node_id": None, "status": "unknown"},
                    ],
                }
            ]
        )
        r = results[0]["result"]
        assert r["healthy"] == 1
        assert r["degraded"] == 1
        assert r["unreachable"] == 1
        assert r["unknown"] == 1
        assert r["total"] == 4

    def test_unrecognised_status_counted_as_unknown(self):
        results = _run_harness(
            [
                {
                    "fn": "masterHealthSummary",
                    "masters": [
                        {"node_id": None, "status": "error"},
                        {"node_id": None, "status": ""},
                        {"node_id": None, "status": "pending"},
                    ],
                }
            ]
        )
        r = results[0]["result"]
        assert r["unknown"] == 3
        assert r["total"] == 3
        assert r["healthy"] == 0

    def test_total_equals_len_of_masters(self):
        masters = [{"node_id": None, "status": "healthy"}] * 7
        results = _run_harness([{"fn": "masterHealthSummary", "masters": masters}])
        assert results[0]["result"]["total"] == 7
