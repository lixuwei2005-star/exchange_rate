from __future__ import annotations

from app.scrapers.base import Scraper, ScrapeResult


class MaybankScraper(Scraper):
    channel_code = "maybank"

    async def fetch(self, base: str, quote: str) -> ScrapeResult:
        raise NotImplementedError("Maybank scraper to be implemented in Phase 5.")
