from __future__ import annotations

from app.scrapers.base import Scraper, ScraperError, ScrapeResult
from app.scrapers.boc import BOCScraper
from app.scrapers.cimb import CIMBScraper
from app.scrapers.mastercard import MastercardScraper
from app.scrapers.maybank import MaybankScraper
from app.scrapers.midmarket import MidmarketScraper
from app.scrapers.unionpay import UnionPayScraper
from app.scrapers.visa import VisaScraper
from app.scrapers.wise import WiseScraper

ALL_SCRAPERS: dict[str, type[Scraper]] = {
    "midmarket": MidmarketScraper,
    "boc": BOCScraper,
    "unionpay": UnionPayScraper,
    "visa": VisaScraper,
    "mastercard": MastercardScraper,
    "wise": WiseScraper,
    "maybank": MaybankScraper,
    "cimb": CIMBScraper,
}

__all__ = [
    "ALL_SCRAPERS",
    "ScrapeResult",
    "Scraper",
    "ScraperError",
]
