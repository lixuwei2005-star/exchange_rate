from __future__ import annotations

import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator


class LoginRequest(BaseModel):
    username: str
    password: str


class MeResponse(BaseModel):
    username: str


# HH:MM, 00:00–23:59. Used for daily_time_cn (Asia/Shanghai / UTC+8).
_HHMM_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
_VALID_SCHEDULE_KINDS = {"interval", "daily"}


class ChannelOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    name_en: str
    name_zh: str
    source_url: str | None
    active: bool
    last_success_at: datetime | None
    last_error_at: datetime | None
    last_error_msg: str | None
    # Per-channel refresh policy. See Channel model + scheduler.
    schedule_kind: str
    interval_minutes: int | None
    daily_time_cn: str | None


class ChannelPatch(BaseModel):
    active: bool | None = None
    name_zh: str | None = None
    name_en: str | None = None
    source_url: str | None = None
    schedule_kind: str | None = None
    interval_minutes: int | None = None
    daily_time_cn: str | None = None

    @field_validator("schedule_kind")
    @classmethod
    def _validate_kind(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if v not in _VALID_SCHEDULE_KINDS:
            raise ValueError("schedule_kind must be 'interval' or 'daily'")
        return v

    @field_validator("interval_minutes")
    @classmethod
    def _validate_interval(cls, v: int | None) -> int | None:
        if v is None:
            return v
        if not 1 <= v <= 1440:
            raise ValueError("interval_minutes must be between 1 and 1440 (one day)")
        return v

    @field_validator("daily_time_cn")
    @classmethod
    def _validate_daily(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if not _HHMM_RE.match(v):
            raise ValueError("daily_time_cn must be HH:MM (00:00–23:59), Asia/Shanghai")
        return v


class SettingOut(BaseModel):
    key: str
    value: str  # masked as "***" if encrypted
    is_encrypted: bool
    updated_at: datetime


class SettingPut(BaseModel):
    value: str


class AITestResult(BaseModel):
    ok: bool
    latency_ms: int | None = None
    model_used: str | None = None
    error: str | None = None


class SummaryAdminOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    base_currency: str
    quote_currency: str
    summary_zh: str
    model_used: str
    generated_at: datetime


class ScrapeLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    channel_code: str | None
    level: str
    message: str
    created_at: datetime
