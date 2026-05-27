from __future__ import annotations

from decimal import Decimal
from typing import ClassVar

import httpx
from bs4 import BeautifulSoup

from app.scrapers._common import make_client, to_decimal
from app.scrapers.base import Scraper, ScraperError, ScrapeResult


class MaybankScraper(Scraper):
    """Maybank Malaysia foreign-exchange counter rates page.

    Maybank quotes in MYR per 1 unit of foreign currency. For CNY -> MYR
    the customer is selling CNY to the bank — that's the bank BUYING CNY —
    so we use the **TT Buying** rate (Telegraphic Transfer, electronic; not
    the Currency Notes rate which is for physical cash and worse).

    Stored direction = MYR per 1 CNY, which matches the native quote — no
    transformation needed once we extract the right column.
    """

    channel_code: ClassVar[str] = "maybank"
    timeout_seconds: ClassVar[int] = 20
    URL: ClassVar[str] = "https://www.maybank2u.com.my/foreign-exchange-rates"
    CURRENCY_LABELS: ClassVar[dict[str, list[str]]] = {
        "CNY": ["CHINESE RENMINBI", "CNY", "CHINA"],
    }

    async def fetch(self, base: str, quote: str) -> ScrapeResult:
        if quote != "MYR":
            raise ScraperError(f"maybank: only MYR quote is supported (got {quote})")
        try:
            async with make_client(self.timeout_seconds) as client:
                resp = await client.get(self.URL)
                resp.raise_for_status()
                html = resp.text
        except httpx.HTTPError as exc:
            raise ScraperError(f"maybank: HTTP error: {exc}") from exc

        tt_buy = self._extract_tt_buy(html, base)
        if tt_buy is None:
            raise ScraperError(f"maybank: could not find {base} TT Buying row")
        rate = tt_buy.quantize(Decimal("0.00000001"))
        if base == "CNY" and quote == "MYR":
            self._sanity_check(rate)
        return ScrapeResult(
            base_currency=base,
            quote_currency=quote,
            rate=rate,
            rate_type="tt_buy",
            raw_payload={"tt_buy": str(rate), "source": "maybank fx counter rates"},
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
            # Heuristic: TT Buying is typically the 2nd numeric column.
            # Skip the currency label and pick the first parseable Decimal.
            for c in cells[1:]:
                try:
                    return to_decimal(c)
                except Exception:
                    continue
        return None
