from __future__ import annotations

from app.scrapers.base import Scraper, ScrapeResult


class VisaScraper(Scraper):
    channel_code = "visa"

    async def fetch(self, base: str, quote: str) -> ScrapeResult:
        raise NotImplementedError("Visa scraper to be implemented in Phase 5.")
