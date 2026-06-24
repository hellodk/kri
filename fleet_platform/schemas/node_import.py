# fleet_platform/schemas/node_import.py
"""Pydantic schemas for bulk node import endpoints (#360)."""

from pydantic import BaseModel, field_validator

from fleet_platform.core.validators import validate_minion_id


class ImportRow(BaseModel):
    minion_id: str
    hostname: str | None = None
    ip: str | None = None
    group: str | None = None
    ssh_user: str | None = None
    status: str = "new"
    reason: str = ""

    _validate_minion_id = field_validator("minion_id")(validate_minion_id)


class ImportValidateRequest(BaseModel):
    source: str
    text: str | None = None
    csv_content: str | None = None
    mapping: dict | None = None


class ImportValidateResponse(BaseModel):
    rows: list[ImportRow]
    summary: dict


class ImportCommitRequest(BaseModel):
    rows: list[ImportRow]
    group_id: str | None = None
    ssh_username: str | None = None
    ssh_password: str | None = None
    ssh_key: str | None = None
    ssh_auth_mode: str | None = None  # "password" | "key"; inferred when omitted
    auto_bootstrap: bool = False


class ImportCommitResponse(BaseModel):
    created: int
    skipped: int
    node_ids: list[str]
    bootstrap_queued: int
