# tests/unit/test_drift_schemas.py
import uuid

from fleet_platform.schemas.drift import (
    BaselineCreate,
    drift_severity,
)
from fleet_platform.schemas.execution import ExecutionJobResponse


def test_drift_severity_clean():
    assert drift_severity(0) == "clean"
    assert drift_severity(5) == "clean"


def test_drift_severity_low():
    assert drift_severity(6) == "low"
    assert drift_severity(20) == "low"


def test_drift_severity_medium():
    assert drift_severity(21) == "medium"
    assert drift_severity(50) == "medium"


def test_drift_severity_high():
    assert drift_severity(51) == "high"
    assert drift_severity(80) == "high"


def test_drift_severity_critical():
    assert drift_severity(81) == "critical"
    assert drift_severity(100) == "critical"


def test_baseline_create_defaults():
    b = BaselineCreate(
        name="global",
        state_json={"packages": {"required": []}},
    )
    assert b.target_type == "global"
    assert b.git_commit_sha == "manual"


def test_execution_job_response():
    j = ExecutionJobResponse(
        id=uuid.uuid4(),
        type="highstate",
        target_type="node",
        triggered_by="salt",
        status="complete",
    )
    assert j.status == "complete"
