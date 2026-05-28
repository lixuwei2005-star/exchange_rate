from __future__ import annotations

import re
from decimal import Decimal
from typing import ClassVar

import httpx
from bs4 import BeautifulSoup, Tag

from app.scrapers.base import Scraper, ScraperError, ScrapeResult

# RHB Malaysia's treasury forex page is server-rendered HTML. Cloudflare
# fronts the host but serves the page to a plain server-side GET (verified
# 2026-05-28) — no JS challenge, unlike Visa. # TODO recheck-2026-11
BROWSER_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

ROW_NEEDLE = "Chinese Renminbi"
COLUMN_HEADER_BUY_TT = "Bank Buy TT"
COLUMN_HEADER_UNIT = "Unit"
# Page-presence marker: appears in the H2 heading above the rates table.
PAGE_MARKER = "Foreign Exchange Rates"


class RHBScraper(Scraper):
    """RHB Bank Malaysia treasury forex rates page.

    URL: https://www.rhbgroup.com/treasury-rates/foreign-exchange/index.html

    Server-renders one forex table. Header row:

        Foreign Currency | Unit | Bank Sell TT/OD | Bank Buy TT | Bank Buy OD

    Each data row carries the currency CODE and NAME in two separate cells
    even though the header has a single 'Foreign Currency' column — so data
    rows have exactly ONE more cell than the header. We account for that
    offset when mapping a header label to its data-cell index.

    For CNY → MYR the customer hands CNY to the bank and gets MYR — the bank
    BUYS CNY — so we use the **Bank Buy TT** column (telegraphic transfer,
    electronic), divided by the row's Unit (100 for CNY). 'OD' columns are
    on-demand instruments; ignored, same policy as the other banks.

    Note: RHB's CNY buy rate carries an unusually wide spread (~0.52 vs a
    ~0.58 mid on 2026-05-28) because CNY has thin liquidity at Malaysian
    banks. That's a real, if uncompetitive, published rate — so this
    scraper widens the sanity floor (see _sanity_check) to avoid false
    "parser bug" rejections when RHB's already-low rate dips further.

    Fee model: fee_estimate is None. Bank spread is already in Bank Buy TT.
    """

    channel_code: ClassVar[str] = "rhb"
    timeout_seconds: ClassVar[int] = 20
    URL: ClassVar[str] = "https://www.rhbgroup.com/treasury-rates/foreign-exchange/index.html"

    async def fetch(self, base: str, quote: str) -> ScrapeResult:
        if quote != "MYR":
            raise ScraperError(f"rhb: only MYR quote is configured (got {quote})")
        if base != "CNY":
            raise ScraperError(f"rhb: only CNY base is configured (got {base})")
        html = await self._fetch_html()
        return self._parse(html, base=base, quote=quote)

    async def _fetch_html(self) -> str:
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout_seconds,
                headers=BROWSER_HEADERS,
                follow_redirects=True,
            ) as client:
                resp = await client.get(self.URL)
                if resp.status_code == 403:
                    raise ScraperError(
                        "rhb: HTTP 403 from server-side GET — likely a WAF block. "
                        "Plain GET worked when this scraper was authored."
                    )
                resp.raise_for_status()
                return resp.text
        except httpx.HTTPError as exc:
            raise ScraperError(f"rhb: HTTP error: {exc}") from exc

    # ---- pure parser --------------------------------------------------

    def _parse(self, html: str, *, base: str, quote: str) -> ScrapeResult:
        if PAGE_MARKER not in html:
            raise ScraperError(
                f"rhb: response missing marker {PAGE_MARKER!r} — page changed or WAF page."
            )

        soup = BeautifulSoup(html, "lxml")
        table = self._find_forex_table(soup)
        if table is None:
            raise ScraperError(f"rhb: no <table> containing {ROW_NEEDLE!r} found on page")

        header = self._find_header(table)
        if header is None:
            raise ScraperError(f"rhb: no header row with {COLUMN_HEADER_BUY_TT!r} found")

        try:
            h_buytt = header.index(COLUMN_HEADER_BUY_TT)
            h_unit = header.index(COLUMN_HEADER_UNIT)
        except ValueError as exc:
            raise ScraperError(f"rhb: required header column missing: {exc}") from exc

        row = self._find_cny_row(table)
        if row is None:
            raise ScraperError("rhb: no row with currency code 'CNY' in forex table")

        # Data rows carry currency CODE + NAME as two cells while the header
        # has a single 'Foreign Currency' column — so every header index past
        # the first maps to data index +1.
        if len(row) != len(header) + 1:
            raise ScraperError(
                f"rhb: CNY row has {len(row)} cells, expected {len(header) + 1} "
                f"(header {len(header)} + 1 for the code/name split)"
            )
        buytt_idx = h_buytt + 1
        unit_idx = h_unit + 1

        buytt_raw = row[buytt_idx]
        unit_raw = row[unit_idx]
        if buytt_raw is None or buytt_raw.upper() == "N/A":
            raise ScraperError("rhb: Bank Buy TT cell is N/A for CNY; cannot compute rate")

        try:
            buytt = Decimal(buytt_raw.replace(",", ""))
            unit = Decimal(unit_raw.replace(",", ""))
        except Exception as exc:
            raise ScraperError(
                f"rhb: cannot parse Bank Buy TT {buytt_raw!r} / Unit {unit_raw!r}: {exc}"
            ) from exc
        if unit <= 0:
            raise ScraperError(f"rhb: non-positive Unit {unit}")

        rate = (buytt / unit).quantize(Decimal("0.00000001"))
        if base == "CNY" and quote == "MYR":
            self._sanity_check(rate)

        return ScrapeResult(
            base_currency=base,
            quote_currency=quote,
            rate=rate,
            rate_type="tt_buy",
            raw_payload={
                "code": row[0],
                "name": row[1] if len(row) > 1 else None,
                "unit": unit_raw,
                "bank_sell_tt_od": row[
                    h_buytt
                ],  # header idx h_buytt → data idx h_buytt (sell col is one before buy)
                "bank_buy_tt": buytt_raw,
                "bank_buy_od": row[buytt_idx + 1] if buytt_idx + 1 < len(row) else None,
            },
            fee_estimate=None,
            fee_currency=None,
        )

    def _sanity_check(self, rate: Decimal) -> None:
        """RHB's CNY TT buy rate carries an unusually wide spread vs mid
        (~0.52 observed 2026-05-28). Widen the floor to 0.45 so a legitimate
        further dip isn't misread as a parser bug. Upper bound unchanged."""
        if not (Decimal("0.45") <= rate <= Decimal("0.8")):
            raise ScraperError(
                f"rhb: sanity check failed: rate={rate} outside CNY->MYR range [0.45, 0.8]"
            )

    # ---- helpers ------------------------------------------------------

    @staticmethod
    def _find_forex_table(soup: BeautifulSoup) -> Tag | None:
        for t in soup.find_all("table"):
            if not isinstance(t, Tag):
                continue
            if ROW_NEEDLE in t.get_text(" ", strip=True):
                return t
        return None

    @staticmethod
    def _find_header(table: Tag) -> list[str] | None:
        for tr in table.find_all("tr"):
            if not isinstance(tr, Tag):
                continue
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
            if COLUMN_HEADER_BUY_TT in cells and COLUMN_HEADER_UNIT in cells:
                return cells
        return None

    @staticmethod
    def _find_cny_row(table: Tag) -> list[str | None] | None:
        """Return the data row whose first cell is exactly 'CNY'. N/A cells
        become None. None if no such row."""
        for tr in table.find_all("tr"):
            if not isinstance(tr, Tag):
                continue
            cells = tr.find_all(["th", "td"])
            if not cells:
                continue
            texts = [c.get_text(" ", strip=True) for c in cells]
            if texts[0].upper() != "CNY":
                continue
            out: list[str | None] = []
            for txt in texts:
                out.append(None if (not txt or txt.upper() == "N/A") else txt)
            return out
        return None

    @staticmethod
    def _extract_last_updated(html: str) -> str | None:
        m = re.search(
            r"(?i)rates?\s+(?:as\s+at|effective|last\s+updated)[^<]{0,80}",
            html,
        )
        return re.sub(r"\s+", " ", m.group(0)).strip() if m else None
