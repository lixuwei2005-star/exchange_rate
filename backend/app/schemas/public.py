from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class LatestRate(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    channel_code: str
    channel_name_zh: str
    rate: Decimal
    rate_type: str
    fee_estimate: Decimal | None = None
    fee_currency: str | None = None
    fetched_at: datetime
    is_stale: bool


class HistoryPoint(BaseModel):
    date: str  # YYYY-MM-DD
    rate: Decimal


class SummaryResponse(BaseModel):
    summary_zh: str | None
    generated_at: datetime | None
    model_used: str | None


class HealthResponse(BaseModel):
    ok: bool
    channels: dict[str, str]  # channel_code -> "fresh" | "stale"
