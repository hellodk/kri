# fleet_platform/schemas/fleet_health.py
import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, computed_field


class NodeHealthSnapshotResponse(BaseModel):
    id: uuid.UUID
    node_id: uuid.UUID
    minion_id: str
    hostname: str | None
    collected_at: datetime
    disk_root_used_gb: Decimal | None
    disk_root_total_gb: Decimal | None
    disk_root_pct: int | None
    disk_root_inodes_pct: int | None
    mem_total_gb: Decimal | None
    mem_available_gb: Decimal | None
    mem_used_pct: int | None
    cpu_load_1m: Decimal | None
    cpu_load_5m: Decimal | None
    cpu_load_15m: Decimal | None
    uptime_seconds: int | None
    gpu_name: str | None
    gpu_vram_mb: int | None
    cpu_power_mw: int | None
    gpu_power_mw: int | None
    thermal_pressure: str | None
    error: str | None

    @computed_field  # type: ignore[misc]
    @property
    def disk_alert(self) -> bool:
        return (self.disk_root_pct or 0) >= 85

    @computed_field  # type: ignore[misc]
    @property
    def mem_alert(self) -> bool:
        return (self.mem_used_pct or 0) >= 90

    @computed_field  # type: ignore[misc]
    @property
    def thermal_alert(self) -> bool:
        return self.thermal_pressure not in (None, "Nominal")

    model_config = {"from_attributes": True}


class CollectResponse(BaseModel):
    status: str
    message: str
