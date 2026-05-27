from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class LoginRequest(BaseModel):
    username: str
    password: str


class MeResponse(BaseModel):
    username: str


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


class ChannelPatch(BaseModel):
    active: bool | None = None
    name_zh: str | None = None
    name_en: str | None = None
    source_url: str | None = None


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
