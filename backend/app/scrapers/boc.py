from __future__ import annotations

from app.scrapers.base import Scraper, ScrapeResult


class BOCScraper(Scraper):
    channel_code = "boc"

    async def fetch(self, base: str, quote: str) -> ScrapeResult:
        raise NotImplementedError("BOC scraper to be implemented in Phase 5.")
