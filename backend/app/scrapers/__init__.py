from __future__ import annotations

from app.scrapers.base import Scraper, ScraperError, ScrapeResult
from app.scrapers.boc import BOCScraper
from app.scrapers.cimb import CIMBScraper
from app.scrapers.mastercard import MastercardScraper
from app.scrapers.midmarket import MidmarketScraper
from app.scrapers.midmarket2 import Midmarket2Scraper
from app.scrapers.publicbank import PublicBankScraper
from app.scrapers.unionpay import UnionPayScraper
from app.scrapers.visa import VisaScraper
from app.scrapers.wise import WiseScraper

# NOTE: maybank was investigated 2026-05-28 and decommissioned — see
# CLAUDE.md §6. Akamai blocks data-center IPs from OCI even with Playwright
# + stealth tweaks; CIMB serves the same Malaysian-bank data dimension
# without that issue. The git history at commits f833360..baa596c carries
# the Playwright-based maybank scraper if we ever revisit.
ALL_SCRAPERS: dict[str, type[Scraper]] = {
    "midmarket": MidmarketScraper,
    "midmarket2": Midmarket2Scraper,
    "boc": BOCScraper,
    "unionpay": UnionPayScraper,
    "visa": VisaScraper,
    "mastercard": MastercardScraper,
    "wise": WiseScraper,
    "cimb": CIMBScraper,
    "publicbank": PublicBankScraper,
}

__all__ = [
    "ALL_SCRAPERS",
    "ScrapeResult",
    "Scraper",
    "ScraperError",
]
