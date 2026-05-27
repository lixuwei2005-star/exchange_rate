from __future__ import annotations

from decimal import Decimal
from typing import ClassVar

import httpx
from bs4 import BeautifulSoup

from app.scrapers._common import make_client, to_decimal
from app.scrapers.base import Scraper, ScraperError, ScrapeResult


class BOCScraper(Scraper):
    """Bank of China exchange rate page (whpj = 外汇牌价).

    The page renders an HTML table where each currency is a row with columns:
        货币名称 | 现汇买入价 | 现钞买入价 | 现汇卖出价 | 现钞卖出价 | 中行折算价 | 发布时间

    The native quote is **CNY per 100 units of foreign currency**. For
    CNY -> MYR we want the "卖出价 (ask)" because the bank is selling MYR
    to the customer (CLAUDE.md §2.4); we use 现汇卖出价, NOT 现钞.

    Stored direction is MYR-per-1-CNY, so:  rate = 100 / 现汇卖出价
    """

    channel_code: ClassVar[str] = "boc"
    timeout_seconds: ClassVar[int] = 20
    URL: ClassVar[str] = "https://www.boc.cn/sourcedb/whpj/"
    CURRENCY_LABELS: ClassVar[dict[str, list[str]]] = {
        "MYR": ["马来西亚林吉特", "林吉特", "MYR"],
    }

    async def fetch(self, base: str, quote: str) -> ScrapeResult:
        if base != "CNY":
            raise ScraperError(f"boc: only CNY base is supported (got {base})")
        try:
            async with make_client(self.timeout_seconds) as client:
                resp = await client.get(self.URL)
                resp.raise_for_status()
                # BOC uses GBK/GB2312 historically. Prefer apparent_encoding.
                resp.encoding = resp.charset_encoding or resp.encoding or "utf-8"
                html = resp.text
        except httpx.HTTPError as exc:
            raise ScraperError(f"boc: HTTP error: {exc}") from exc

        ask_per_100 = self._extract_ask_for_currency(html, quote)
        if ask_per_100 is None:
            raise ScraperError(f"boc: could not find row for {quote} in HTML")
        # CNY per 100 quote -> MYR per 1 CNY = 100 / (CNY per 100 MYR)
        rate = (Decimal("100") / ask_per_100).quantize(Decimal("0.00000001"))
        self._sanity_check(rate)

        return ScrapeResult(
            base_currency=base,
            quote_currency=quote,
            rate=rate,
            rate_type="bank_ask",
            raw_payload={"ask_per_100_units": str(ask_per_100), "source": "boc whpj"},
        )

    def _extract_ask_for_currency(self, html: str, quote: str) -> Decimal | None:
        """Find the row matching the target currency, return 现汇卖出价 as Decimal."""
        labels = self.CURRENCY_LABELS.get(quote, [quote])
        soup = BeautifulSoup(html, "lxml")
        for tr in soup.find_all("tr"):
            cells = [c.get_text(strip=True) for c in tr.find_all("td")]
            if len(cells) < 7:
                continue
            name = cells[0]
            if not any(lbl in name for lbl in labels):
                continue
            # cells[3] = 现汇卖出价 (cash remit ask)
            raw_ask = cells[3]
            if not raw_ask:
                continue
            try:
                return to_decimal(raw_ask)
            except Exception:
                continue
        return None
