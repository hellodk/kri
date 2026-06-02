# fleet_platform/schemas/playbook.py
import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel


class PlaybookEntryResponse(BaseModel):
    filename: str
    name: str
    description: str | None
    entry_type: str
    default_vars: dict
    var_descriptions: dict = {}    # {var_name: help_text} — shown in kri run modal
    lint_errors: list[str] = []
    source_dir: str | None = None   # absolute path of the directory this was discovered in


class PlaybookRunRequest(BaseModel):
    playbook: str
    target_type: str
    target_id: str
    extravars: dict = {}
    ssh_username: str | None = None   # overrides platform setting ssh_bootstrap_username
    ssh_password: str | None = None   # overrides platform setting ssh_bootstrap_password
    verbosity: int = 0                # 0=default, 1=-v, 2=-vv, 3=-vvv, 4=-vvvv


class PlaybookRunResponse(BaseModel):
    job_id: uuid.UUID
    playbook: str
    target_label: str
    status: str
    message: str


class AnsibleJobResponse(BaseModel):
    id: uuid.UUID
    playbook: str
    target_type: str
    target_label: str
    target_id: str | None = None   # UUID of the targeted node/group — needed for re-run
    extravars: dict
    status: str
    triggered_by: str
    started_at: datetime | None
    completed_at: datetime | None
    stdout: str | None
    rc: int | None
    verbosity: int = 0
    created_at: datetime
    celery_task_id: str | None = None
    cancelled_at: datetime | None = None


class PlaybookSourceRequest(BaseModel):
    type: Literal["local", "git"]
    path: str | None = None       # for local
    url: str | None = None        # for git
    branch: str = "main"          # for git
    label: str | None = None      # display name
    local_path: str | None = None  # override clone destination for git
    ssh_key: str | None = None    # PEM private key content for private repos
    token: str | None = None      # Personal access token / GitHub token


class PlaybookSourceResponse(BaseModel):
    index: int
    type: str
    path: str | None = None
    url: str | None = None
    branch: str | None = None
    label: str | None = None
    local_path: str | None = None


class PlaybookSourcesImportRequest(BaseModel):
    csv: str


class PlaybookSourceSyncResult(BaseModel):
    results: list[dict[str, Any]]


class PlaybookSourceValidateRequest(BaseModel):
    type: Literal["local", "git"]
    path: str | None = None
    url: str | None = None
    branch: str = "main"
    ssh_key: str | None = None    # PEM private key content for private repos
    token: str | None = None      # Personal access token / GitHub token


class PlaybookSourceValidateResponse(BaseModel):
    valid: bool
    error: str | None = None
    warnings: list[str] = []
    playbook_count: int = 0
    role_count: int = 0
    entries: list[PlaybookEntryResponse] = []
    logs: list[str] = []
