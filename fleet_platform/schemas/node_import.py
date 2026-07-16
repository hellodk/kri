# fleet_platform/schemas/node_import.py
"""Pydantic schemas for bulk node import endpoints (#360)."""

from pydantic import BaseModel


class ImportRow(BaseModel):
    # NOTE: minion_id is intentionally NOT hard-validated here. ImportRow is the
    # transport for the dry-run *validate* response, which must be able to
    # represent rows that FAILED validation (status="invalid") so the UI can
    # show the user exactly which rows were rejected and why. Raising at parse
    # time would 500 the validate endpoint instead of reporting invalid rows.
    # Format enforcement happens in node_import.validate_row (soft, categorising)
    # and again defensively on the commit path (see fleet.import_commit), so a
    # bad minion_id can never be persisted.
    minion_id: str
    hostname: str | None = None
    ip: str | None = None
    group: str | None = None
    ssh_user: str | None = None
    status: str = "new"
    reason: str = ""
    ssh_state: str | None = None
    ssh_detail: str | None = None


class ImportValidateRequest(BaseModel):
    source: str
    text: str | None = None
    csv_content: str | None = None
    mapping: dict | None = None
    # Operator-supplied SSH creds (#1012) — used only to probe reachability
    # during validate; never persisted here. Mirrors ImportCommitRequest.
    ssh_username: str | None = None
    ssh_password: str | None = None
    ssh_key: str | None = None
    ssh_auth_mode: str | None = None  # "password" | "key"; inferred when omitted


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
    # Master-first bootstrap (#1019): see BootstrapRequest.as_master.
    as_master: bool = False


class ImportCommitResponse(BaseModel):
    created: int
    skipped: int
    node_ids: list[str]
    bootstrap_queued: int
