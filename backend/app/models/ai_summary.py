from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class AISummary(Base):
    __tablename__ = "ai_summaries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    base_currency: Mapped[str] = mapped_column(
        String(8), ForeignKey("currencies.code"), nullable=False
    )
    quote_currency: Mapped[str] = mapped_column(
        String(8), ForeignKey("currencies.code"), nullable=False
    )
    summary_zh: Mapped[str] = mapped_column(Text, nullable=False)
    model_used: Mapped[str] = mapped_column(String(128), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index(
            "ix_ai_summaries_pair_generated",
            "base_currency",
            "quote_currency",
            "generated_at",
        ),
    )
