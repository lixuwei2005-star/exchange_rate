from __future__ import annotations

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Currency(Base):
    __tablename__ = "currencies"

    code: Mapped[str] = mapped_column(String(8), primary_key=True)  # ISO 4217
    name_en: Mapped[str] = mapped_column(String(64))
    name_zh: Mapped[str] = mapped_column(String(64))
