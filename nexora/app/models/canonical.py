from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class SoftwareProduct(BaseModel):
    software_id: str
    software_name: str
    publisher: str | None = None


class LicensePool(BaseModel):
    license_pool_id: str
    software: SoftwareProduct
    source: str = "digimon"


class LicenseStock(BaseModel):
    license_manager: str | None = None
    license_pool_id: str
    software_id: str
    software_name: str
    timestamp: datetime
    capacity: int = Field(ge=0)
    used: int = Field(ge=0)
    available: int = Field(ge=0)
    source: str


class LicenseUsage(BaseModel):
    license_pool_id: str
    software_id: str
    software_name: str
    timestamp: datetime
    capacity: int = Field(ge=0)
    used: int = Field(ge=0)
    available: int = Field(ge=0)
    user_id: str | None = None
    device_id: str | None = None
    source: str


class UsageSnapshot(BaseModel):
    snapshot_id: str
    timestamp: datetime
    source: str
    usage: list[LicenseUsage]
    stock: list[LicenseStock]


class Trend(BaseModel):
    license_pool_id: str
    software_name: str
    period_start: datetime
    period_end: datetime
    average_used: float
    maximum_used: int
    p95_used: float
    capacity: int
    utilization_rate: float
    previous_period_change: float | None
    daily: list[dict[str, int | str]]


class InactiveCandidate(BaseModel):
    license_pool_id: str
    software_name: str
    utilization_rate: float
    observed_days: int
    recovery_potential: int
    confidence: Literal["low", "medium", "high"]
    reason: str
    period_start: datetime
    period_end: datetime


class SaturationRisk(BaseModel):
    license_pool_id: str
    software_name: str
    level: Literal["low", "medium", "high"]
    growth_per_day: float
    remaining_capacity: int
    estimated_saturation_date: datetime | None
    reason: str


class AnalyticsSummary(BaseModel):
    generated_at: datetime
    total_capacity: int
    total_used: int
    total_available: int
    utilization_rate: float
    pools_at_risk: int
    pools_total: int
    recovery_potential: int
    trends: list[Trend]
    inactive: list[InactiveCandidate]
    risks: list[SaturationRisk]


class StorageLayer(BaseModel):
    name: str
    count: int
    first_date: str | None
    last_date: str | None
    sample_keys: list[str]


class PlatformStatus(BaseModel):
    demo_tools_enabled: bool = False
    mode: Literal["mock", "digimon"]
    checked_at: datetime
    spark_master: str
    underutilization_threshold: float
    recovery_buffer_rate: float
    layers: list[StorageLayer]


class DemoGenerationRequest(BaseModel):
    days: int = Field(default=365, ge=30, le=730)
