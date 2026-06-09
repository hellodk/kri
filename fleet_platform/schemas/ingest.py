# fleet_platform/schemas/ingest.py
from datetime import datetime

from pydantic import BaseModel


class GrainIngestPayload(BaseModel):
    minion_id: str
    grains: dict


class ExecutionIngestPayload(BaseModel):
    minion_id: str
    jid: str
    return_data: dict
    fun: str
    retcode: int = 0
    success: bool = True


class SBOMIngestAck(BaseModel):
    status: str = "queued"
    node_id: str


class ProcessStatItem(BaseModel):
    pid: int
    name: str
    cmdline: str | None = None
    cpu_pct: float | None = None
    mem_rss_bytes: int | None = None
    mem_pct: float | None = None
    num_threads: int | None = None
    status: str | None = None
    username: str | None = None
    io_read_bytes: int | None = None
    io_write_bytes: int | None = None
    is_llm: bool = False


class ProcessStatsIngestPayload(BaseModel):
    minion_id: str
    collected_at: datetime | None = None  # defaults to server now() when absent
    processes: list[ProcessStatItem]
