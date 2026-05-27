from __future__ import annotations

from app.scrapers.base import Scraper, ScrapeResult


class MastercardScraper(Scraper):
    channel_code = "mastercard"

    async def fetch(self, base: str, quote: str) -> ScrapeResult:
        raise NotImplementedError("Mastercard scraper to be implemented in Phase 5.")
