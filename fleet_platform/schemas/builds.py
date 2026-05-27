# fleet_platform/schemas/builds.py
from datetime import datetime

from pydantic import BaseModel, field_validator


class JenkinsBuildIngestPayload(BaseModel):
    job_name: str
    build_number: int
    result: str  # SUCCESS, FAILURE, UNSTABLE, ABORTED, NOT_BUILT
    duration_ms: int | None = None
    started_at: datetime
    test_pass: int | None = None
    test_fail: int | None = None
    test_total: int | None = None
    node_name: str | None = None
    branch: str | None = None

    @field_validator("result")
    @classmethod
    def validate_result(cls, v: str) -> str:
        allowed = {"SUCCESS", "FAILURE", "UNSTABLE", "ABORTED", "NOT_BUILT"}
        if v not in allowed:
            raise ValueError(f"result must be one of {allowed}")
        return v

    @field_validator("job_name")
    @classmethod
    def validate_job_name(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("job_name cannot be empty")
        return v.strip()


class JenkinsBuildResponse(BaseModel):
    id: str
    job_name: str
    build_number: int
    result: str
    duration_ms: int | None
    started_at: datetime
    test_pass: int | None
    test_fail: int | None
    test_total: int | None
    node_name: str | None
    branch: str | None
