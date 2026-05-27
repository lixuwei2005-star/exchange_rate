from __future__ import annotations

from decimal import Decimal
from typing import ClassVar

import httpx
from bs4 import BeautifulSoup

from app.scrapers._common import make_client, to_decimal
from app.scrapers.base import Scraper, ScraperError, ScrapeResult


class CIMBScraper(Scraper):
    """CIMB Malaysia foreign-exchange counter rates page.

    Same shape as Maybank: MYR per 1 unit foreign currency, and for CNY -> MYR
    we use the **TT Buying** rate (the bank buys foreign from the customer).
    """

    channel_code: ClassVar[str] = "cimb"
    timeout_seconds: ClassVar[int] = 20
    URL: ClassVar[str] = (
        "https://www.cimb.com.my/en/personal/help-support/rates/"
        "foreign-exchange-counter-rates.html"
    )
    CURRENCY_LABELS: ClassVar[dict[str, list[str]]] = {
        "CNY": ["CHINA", "CNY", "RENMINBI"],
    }

    async def fetch(self, base: str, quote: str) -> ScrapeResult:
        if quote != "MYR":
            raise ScraperError(f"cimb: only MYR quote is supported (got {quote})")
        try:
            async with make_client(self.timeout_seconds) as client:
                resp = await client.get(self.URL)
                resp.raise_for_status()
                html = resp.text
        except httpx.HTTPError as exc:
            raise ScraperError(f"cimb: HTTP error: {exc}") from exc

        tt_buy = self._extract_tt_buy(html, base)
        if tt_buy is None:
            raise ScraperError(f"cimb: could not find {base} TT Buying row")
        rate = tt_buy.quantize(Decimal("0.00000001"))
        if base == "CNY" and quote == "MYR":
            self._sanity_check(rate)
        return ScrapeResult(
            base_currency=base,
            quote_currency=quote,
            rate=rate,
            rate_type="tt_buy",
            raw_payload={"tt_buy": str(rate), "source": "cimb fx counter rates"},
        )

    def _extract_tt_buy(self, html: str, base: str) -> Decimal | None:
        labels = [s.upper() for s in self.CURRENCY_LABELS.get(base, [base])]
        soup = BeautifulSoup(html, "lxml")
        for tr in soup.find_all("tr"):
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
            if len(cells) < 2:
                continue
            row_label = cells[0].upper()
            if not any(lbl in row_label for lbl in labels):
                continue
            for c in cells[1:]:
                try:
                    return to_decimal(c)
                except Exception:
                    continue
        return None
