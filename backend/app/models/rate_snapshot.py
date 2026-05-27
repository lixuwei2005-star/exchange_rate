from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class RateSnapshot(Base):
    __tablename__ = "rate_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    channel_code: Mapped[str] = mapped_column(
        String(32), ForeignKey("channels.code"), nullable=False
    )
    base_currency: Mapped[str] = mapped_column(
        String(8), ForeignKey("currencies.code"), nullable=False
    )
    quote_currency: Mapped[str] = mapped_column(
        String(8), ForeignKey("currencies.code"), nullable=False
    )
    # quote per 1 base, always normalized
    rate: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    rate_type: Mapped[str] = mapped_column(String(32), nullable=False)
    fee_estimate: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    fee_currency: Mapped[str | None] = mapped_column(String(8), nullable=True)
    raw_payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index(
            "ix_rate_snapshots_channel_pair_fetched",
            "channel_code",
            "base_currency",
            "quote_currency",
            "fetched_at",
        ),
    )
