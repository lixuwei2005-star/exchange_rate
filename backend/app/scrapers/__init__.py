from __future__ import annotations

from app.scrapers.affin import AffinScraper
from app.scrapers.alliance import AllianceScraper
from app.scrapers.ambank import AmBankScraper
from app.scrapers.base import Scraper, ScraperError, ScrapeResult
from app.scrapers.boc import BOCScraper
from app.scrapers.cimb import CIMBScraper
from app.scrapers.hlb import HLBScraper
from app.scrapers.hsbc import HSBCScraper
from app.scrapers.icbc import ICBCScraper
from app.scrapers.mastercard import MastercardScraper
from app.scrapers.maybank import MaybankScraper
from app.scrapers.midmarket import MidmarketScraper
from app.scrapers.midmarket2 import Midmarket2Scraper
from app.scrapers.midmarket3 import Midmarket3Scraper
from app.scrapers.ocbc import OCBCScraper
from app.scrapers.publicbank import PublicBankScraper
from app.scrapers.rhb import RHBScraper
from app.scrapers.sc import StandardCharteredScraper
from app.scrapers.unionpay import UnionPayScraper
from app.scrapers.visa import VisaScraper
from app.scrapers.wise import WiseScraper

# NOTE: maybank was decommissioned 2026-05-28 (Akamai blocks OCI's IP even
# via Playwright) and RE-ADDED 2026-05-30 via Firecrawl — the single
# sanctioned exception to the no-proxy rule (CLAUDE.md §6/§7). It needs
# FIRECRAWL_API_KEY set or it raises a clear error and stays stale.
ALL_SCRAPERS: dict[str, type[Scraper]] = {
    "midmarket": MidmarketScraper,
    "midmarket2": Midmarket2Scraper,
    "midmarket3": Midmarket3Scraper,
    "boc": BOCScraper,
    "icbc": ICBCScraper,
    "unionpay": UnionPayScraper,
    "visa": VisaScraper,
    "mastercard": MastercardScraper,
    "wise": WiseScraper,
    "maybank": MaybankScraper,
    "cimb": CIMBScraper,
    "publicbank": PublicBankScraper,
    "rhb": RHBScraper,
    "hlb": HLBScraper,
    "alliance": AllianceScraper,
    "ambank": AmBankScraper,
    "hsbc": HSBCScraper,
    "ocbc": OCBCScraper,
    "sc": StandardCharteredScraper,
    "affin": AffinScraper,
}

__all__ = [
    "ALL_SCRAPERS",
    "ScrapeResult",
    "Scraper",
    "ScraperError",
]
