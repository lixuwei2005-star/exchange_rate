from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import ClassVar

import httpx
from bs4 import BeautifulSoup, Tag

from app.scrapers.base import Scraper, ScraperError, ScrapeResult

# HSBC Malaysia's currency-rate page is server-rendered HTML reachable with a
# plain GET + the project UA (verified 2026-05-30: HTTP 200, rates inline, no
# bot wall — curl_cffi not needed).
PROJECT_HEADERS: dict[str, str] = {
    "User-Agent": "rate.005917.xyz contact: lixuwei2005@gmail.com",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

COLUMN_HEADER_BUY = "TT Buy"
COLUMN_HEADER_SELL = "TT Sell"
ROW_CODE = "CNY"
# Structural marker: the TT board's Buy header. Absent → page changed / blocked.
PAGE_MARKER = COLUMN_HEADER_BUY
# The per-row multiplier isn't a column here; it's in the table caption,
# e.g. "Exchange Rates in Units of Local Currency to 100 Units of Foreign
# Currency". CNY lives in the per-100 table.
_CAPTION_UNIT_RE = re.compile(r"to\s+(\d+)\s+units?\s+of\s+foreign\s+currency", re.I)
_UNAVAILABLE = {"", "-", "--", "N/A", "NA"}


class HSBCScraper(Scraper):
    """HSBC Bank (Malaysia) currency-rate board.

    URL: /investments/products/foreign-exchange/currency-rate/

    The page server-renders several ``<table>``s (a per-1-unit TT table, a
    per-100-units TT table, and cash/Notes tables). The TT tables' header is:

        Currency | Currency Name | TT Sell | TT Buy

    and the table caption states the multiplier ("... to 100 Units of Foreign
    Currency"). CNY sits in the per-100 table. The currency code is in the
    row's <th>, so a header-label lookup maps to the same index in the row.

    For CNY → MYR the customer hands CNY to the bank and gets MYR — the bank
    BUYS CNY — so we use **TT Buy** ÷ caption-multiplier (100 for CNY). The
    Notes (cash) tables don't have a 'TT Buy' header, so they're skipped.

    Fee model: fee_estimate is None — the spread is already in TT Buy.
    """

    channel_code: ClassVar[str] = "hsbc"
    timeout_seconds: ClassVar[int] = 20
    URL: ClassVar[str] = (
        "https://www.hsbc.com.my/investments/products/foreign-exchange/currency-rate/"
    )

    async def fetch(self, base: str, quote: str) -> ScrapeResult:
        if quote != "MYR":
            raise ScraperError(f"hsbc: only MYR quote is configured (got {quote})")
        if base != "CNY":
            raise ScraperError(f"hsbc: only CNY base is configured (got {base})")
        html = await self._fetch_html()
        return self._parse(html, base=base, quote=quote)

    async def _fetch_html(self) -> str:
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout_seconds,
                headers=PROJECT_HEADERS,
                follow_redirects=True,
            ) as client:
                resp = await client.get(self.URL)
                if resp.status_code == 403:
                    raise ScraperError(
                        "hsbc: HTTP 403 from server-side GET — likely a WAF block. "
                        "Plain GET worked when this scraper was authored."
                    )
                resp.raise_for_status()
                return resp.text
        except httpx.HTTPError as exc:
            raise ScraperError(f"hsbc: HTTP error: {exc}") from exc

    # ---- pure parser --------------------------------------------------

    def _parse(self, html: str, *, base: str, quote: str) -> ScrapeResult:
        if PAGE_MARKER not in html:
            raise ScraperError(
                f"hsbc: response missing marker {PAGE_MARKER!r} — page changed or WAF page."
            )

        soup = BeautifulSoup(html, "lxml")
        found = self._find_tt_table_with_cny(soup)
        if found is None:
            raise ScraperError(
                f"hsbc: no TT <table> (header {COLUMN_HEADER_BUY!r}) with a {ROW_CODE!r} row"
            )
        header, row, caption = found

        try:
            i_buy = header.index(COLUMN_HEADER_BUY)
        except ValueError as exc:
            raise ScraperError(f"hsbc: {COLUMN_HEADER_BUY!r} column missing: {exc}") from exc
        if i_buy >= len(row):
            raise ScraperError(
                f"hsbc: CNY row has {len(row)} cells, no index {i_buy} for {COLUMN_HEADER_BUY}"
            )

        buy_raw = row[i_buy]
        if buy_raw is None or buy_raw.upper() in _UNAVAILABLE:
            raise ScraperError(f"hsbc: {COLUMN_HEADER_BUY} is unavailable ({buy_raw!r}) for CNY")

        m = _CAPTION_UNIT_RE.search(caption or "")
        if not m:
            raise ScraperError(
                f"hsbc: could not read the per-N-units multiplier from caption {caption!r}"
            )
        multiplier = int(m.group(1))
        if multiplier <= 0:
            raise ScraperError(f"hsbc: non-positive multiplier {multiplier}")

        try:
            buy = Decimal(buy_raw.replace(",", ""))
        except InvalidOperation as exc:
            raise ScraperError(
                f"hsbc: cannot parse {COLUMN_HEADER_BUY} {buy_raw!r}: {exc}"
            ) from exc
        if buy <= 0:
            raise ScraperError(f"hsbc: {COLUMN_HEADER_BUY} is {buy_raw!r} (zero) for CNY")

        rate = (buy / Decimal(multiplier)).quantize(Decimal("0.00000001"))
        if base == "CNY" and quote == "MYR":
            self._sanity_check(rate)

        return ScrapeResult(
            base_currency=base,
            quote_currency=quote,
            rate=rate,
            rate_type="tt_buy",
            raw_payload={
                "tt_buy": buy_raw,
                "multiplier": multiplier,
                "tt_sell": (
                    row[header.index(COLUMN_HEADER_SELL)] if COLUMN_HEADER_SELL in header else None
                ),
                "caption": caption,
            },
            fee_estimate=None,
            fee_currency=None,
        )

    # ---- helpers ------------------------------------------------------

    @staticmethod
    def _find_tt_table_with_cny(
        soup: BeautifulSoup,
    ) -> tuple[list[str], list[str | None], str | None] | None:
        """Find the TT table (header has 'TT Buy') that contains the CNY row.
        Returns (header_cells, cny_row_cells, caption_text) or None."""
        for t in soup.find_all("table"):
            if not isinstance(t, Tag):
                continue
            header: list[str] | None = None
            for tr in t.find_all("tr"):
                cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
                if COLUMN_HEADER_BUY in cells and COLUMN_HEADER_SELL in cells:
                    header = cells
                    break
            if header is None:
                continue
            row = HSBCScraper._find_cny_row(t)
            if row is None:
                continue
            cap = t.find("caption")
            caption = cap.get_text(" ", strip=True) if isinstance(cap, Tag) else None
            return header, row, caption
        return None

    @staticmethod
    def _find_cny_row(table: Tag) -> list[str | None] | None:
        """Row whose first cell (the currency code <th>) == ROW_CODE."""
        for tr in table.find_all("tr"):
            if not isinstance(tr, Tag):
                continue
            cells = tr.find_all(["th", "td"])
            if not cells:
                continue
            texts = [c.get_text(" ", strip=True) for c in cells]
            if texts[0].strip().upper() != ROW_CODE:
                continue
            return [None if (not t or t.upper() in _UNAVAILABLE) else t for t in texts]
        return None
