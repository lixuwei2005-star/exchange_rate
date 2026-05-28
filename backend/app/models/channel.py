from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Channel(Base):
    __tablename__ = "channels"

    code: Mapped[str] = mapped_column(String(32), primary_key=True)
    name_en: Mapped[str] = mapped_column(String(128))
    name_zh: Mapped[str] = mapped_column(String(128))
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_msg: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Per-channel refresh policy, editable via /admin/channels.
    # `schedule_kind` is 'interval' (default) or 'daily'. The scheduler in
    # app/scheduler.py picks IntervalTrigger or CronTrigger(Asia/Shanghai)
    # from these columns. When both detail columns are NULL the scheduler
    # falls back to DEFAULT_INTERVAL_MINUTES.
    schedule_kind: Mapped[str] = mapped_column(
        String(16), default="interval", server_default="interval", nullable=False
    )
    interval_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # HH:MM in Asia/Shanghai (UTC+8). Server runs in SGT but UnionPay etc
    # publish at Beijing wall-clock times, so we store + display in CN time.
    daily_time_cn: Mapped[str | None] = mapped_column(String(5), nullable=True)
