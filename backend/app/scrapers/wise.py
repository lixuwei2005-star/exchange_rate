from __future__ import annotations

from app.scrapers.base import Scraper, ScrapeResult


class WiseScraper(Scraper):
    channel_code = "wise"

    async def fetch(self, base: str, quote: str) -> ScrapeResult:
        raise NotImplementedError("Wise scraper to be implemented in Phase 5.")
