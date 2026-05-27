from __future__ import annotations

from abc import ABC, abstractmethod
from decimal import Decimal
from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict

RateType = Literal[
    "bank_ask",  # Chinese bank selling foreign for CNY (CNY -> foreign)
    "bank_bid",  # Chinese bank buying foreign, giving CNY (foreign -> CNY)
    "tt_buy",  # MY bank buying foreign, giving MYR (foreign -> MYR)
    "tt_sell",  # MY bank selling foreign for MYR (MYR -> foreign)
    "card_network",  # Visa / MC / UnionPay network rate
    "p2p",  # Wise et al
    "midmarket",  # reference
]


class ScraperError(RuntimeError):
    """Raised by a scraper on any failure. Scheduler catches and logs."""


class ScrapeResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    base_currency: str  # ISO 4217, e.g. "CNY"
    quote_currency: str  # ISO 4217, e.g. "MYR"
    rate: Decimal  # quote per 1 base (always normalized)
    rate_type: RateType
    raw_payload: dict
    fee_estimate: Decimal | None = None
    fee_currency: str | None = None


class Scraper(ABC):
    channel_code: ClassVar[str]
    timeout_seconds: ClassVar[int] = 15

    @abstractmethod
    async def fetch(self, base: str, quote: str) -> ScrapeResult:
        """Fetch the latest rate for the given pair, normalized to quote-per-1-base."""

    def _sanity_check(self, rate: Decimal) -> None:
        """For CNY->MYR, stored rate must be in [0.5, 0.8] (see CLAUDE.md §2.6).
        Override in subclass for other pairs. Raises ScraperError if out of range."""
        if not (Decimal("0.5") <= rate <= Decimal("0.8")):
            raise ScraperError(
                f"sanity check failed: rate={rate} outside expected CNY->MYR range [0.5, 0.8]"
            )
