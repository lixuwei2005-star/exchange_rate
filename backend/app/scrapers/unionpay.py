from __future__ import annotations

from app.scrapers.base import Scraper, ScrapeResult


class UnionPayScraper(Scraper):
    channel_code = "unionpay"

    async def fetch(self, base: str, quote: str) -> ScrapeResult:
        raise NotImplementedError("UnionPay scraper to be implemented in Phase 5.")
