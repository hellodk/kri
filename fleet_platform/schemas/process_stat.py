from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class ProcessStatOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    pid: int
    name: str
    cmdline: str | None = None
    cpu_pct: Decimal | None = None
    mem_rss_bytes: int | None = None
    mem_pct: Decimal | None = None
    num_threads: int | None = None
    status: str | None = None
    username: str | None = None
    io_read_bytes: int | None = None
    io_write_bytes: int | None = None
    is_llm: bool = False
    collected_at: datetime
