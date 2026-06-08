# fleet_platform/schemas/ingest.py
from datetime import datetime

from pydantic import BaseModel, Field

# Hard cap on per-process rows accepted in a single process_stats payload.
# Overflow is dropped and logged at the endpoint — never silently truncated.
MAX_PROCESSES_PER_PAYLOAD = 250


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
    """A single per-process resource sample from the node-side psutil collector."""

    pid: int
    name: str
    cmdline: str | None = None
    cpu_pct: float
    mem_rss_bytes: int
    mem_pct: float
    num_threads: int
    status: str | None = None
    username: str | None = None
    io_read_bytes: int | None = None
    io_write_bytes: int | None = None
    is_llm: bool = False


class ProcessStatsIngestPayload(BaseModel):
    minion_id: str
    # Optional — when omitted the endpoint stamps datetime.now(UTC) at ingest.
    collected_at: datetime | None = None
    processes: list[ProcessStatItem] = Field(default_factory=list)

    def capped_processes(self) -> tuple[list[ProcessStatItem], int]:
        """Return (kept, dropped_count), capping at MAX_PROCESSES_PER_PAYLOAD.

        Truncation is explicit so the caller can log the overflow rather than
        silently dropping rows.
        """
        overflow = len(self.processes) - MAX_PROCESSES_PER_PAYLOAD
        if overflow <= 0:
            return self.processes, 0
        return self.processes[:MAX_PROCESSES_PER_PAYLOAD], overflow
