from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class LatestRate(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    channel_code: str
    channel_name_zh: str
    # `rate` is the channel's effective rate (already reflects any baked-in
    # markup or fee that the channel exposes via its quote — see §2.5 of
    # CLAUDE.md). Used by the homepage's '你能拿到' column.
    rate: Decimal
    # `headline_rate` is the channel's advertised pre-fee rate, used by the
    # pure-rate comparison table. For most channels it equals `rate`; for
    # Wise (whose stored rate is after-fee) it's the mid-market rate that
    # Wise quotes — extracted from raw_payload at API time.
    headline_rate: Decimal
    rate_type: str
    # Absolute fee at the channel's reference quote amount, mostly useful as
    # a static fallback. Wise's fee has a sizable fixed component, so the
    # homepage queries /api/quote/wise for the user's actual amount instead
    # of relying on this snapshot value.
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


class ConfigResponse(BaseModel):
    # Which channel's rate the homepage hero ("1 MYR = X CNY") shows.
    # Admin-editable via settings key `display.headline_channel`.
    headline_channel: str
