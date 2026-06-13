# fleet_platform/schemas/drift.py
import uuid
from datetime import datetime

from pydantic import BaseModel


def drift_severity(score: int) -> str:
    """Map a 0–100 drift score to a severity label."""
    if score <= 5:
        return "clean"
    if score <= 20:
        return "low"
    if score <= 50:
        return "medium"
    if score <= 80:
        return "high"
    return "critical"


class DriftSummaryResponse(BaseModel):
    node_id: uuid.UUID
    hostname: str | None
    drift_score: int
    severity: str
    computed_at: datetime | None
    baseline_name: str | None


class DriftRecordResponse(BaseModel):
    node_id: uuid.UUID
    baseline_id: uuid.UUID | None
    baseline_name: str | None
    computed_at: datetime
    drift_score: int
    severity: str
    missing_packages: list[dict]
    extra_packages: list[dict]
    version_mismatches: list[dict]
    service_drift: list[dict]
    config_drift: list[dict]

    model_config = {"from_attributes": True}


class BaselineCreate(BaseModel):
    name: str
    description: str | None = None
    target_type: str = "global"  # global | group | node
    target_id: uuid.UUID | None = None
    state_json: dict
    git_commit_sha: str = "manual"
    # When set, the baseline only applies to nodes whose derived os_family
    # matches. Use the canonical Salt grain values: 'Darwin', 'Linux',
    # 'FreeBSD', 'Windows'. Omit (None) for OS-agnostic baselines.
    os_family: str | None = None


class BaselineResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    target_type: str
    target_id: uuid.UUID | None
    git_commit_sha: str
    version: int
    os_family: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
