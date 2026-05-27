from __future__ import annotations

from app.scrapers.base import Scraper, ScrapeResult


class MidmarketScraper(Scraper):
    """Frankfurter midmarket reference rate. Implemented end-to-end in Phase 4."""

    channel_code = "midmarket"

    async def fetch(self, base: str, quote: str) -> ScrapeResult:
        raise NotImplementedError("Midmarket scraper is wired up in Phase 4.")
