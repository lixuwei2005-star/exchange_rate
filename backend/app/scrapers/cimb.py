from __future__ import annotations

from app.scrapers.base import Scraper, ScrapeResult


class CIMBScraper(Scraper):
    channel_code = "cimb"

    async def fetch(self, base: str, quote: str) -> ScrapeResult:
        raise NotImplementedError("CIMB scraper to be implemented in Phase 5.")
