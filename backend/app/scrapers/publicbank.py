from __future__ import annotations

import re
from decimal import Decimal
from typing import ClassVar

import httpx
from bs4 import BeautifulSoup, Tag

from app.scrapers.base import Scraper, ScraperError, ScrapeResult

# Same browser-shape headers we use for other server-rendered pages. Public
# Bank's /en/rates-charges/forex/ returns a clean HTML doc to a plain
# server-side GET — no Akamai-style interstitial as far as 2026-05-28.
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

# Page-presence marker: also fronts the "as at <date> <time>" timestamp
# paragraph just below the H1. If this text is missing we're either looking
# at a junk page or a WAF interstitial.
PAGE_MARKER = "Foreign Exchange Rate"

# We pick the row by currency name and the column by header text; both are
# more resilient than hardcoded indices if Public Bank reshuffles its page.
ROW_NEEDLE = "Chinese Renminbi"
COLUMN_HEADER_BUYING_TT = "Buying TT"
COLUMN_HEADER_CURRENCY = "Currency"


class PublicBankScraper(Scraper):
    """Public Bank Malaysia (Public Bank Berhad / PBB) forex rates page.

    URL: https://www.pbebank.com/en/rates-charges/forex/

    The page server-renders one forex table whose rows look like:

        '100 Chinese Renminbi (Non Trade)'
        | Selling TT/OD | Buying TT | Buying OD
        | Currency Notes Selling | Currency Notes Buying

    The multiplier (100 in the CNY row's case) is baked into the row label
    itself, not into a section heading. We parse it out with a regex.

    For CNY → MYR the customer hands CNY to the bank and walks away with
    MYR — i.e. the bank BUYS CNY. So we use **Buying TT** and divide by
    the label's multiplier. (Currency Notes columns are physical-cash
    rates for travellers; we ignore them.)

    Fee model: fee_estimate is None. The bank's spread is already in
    Buying TT; the separate RM TT charge applies to outbound transfers,
    not to this counter-rate comparison.
    """

    channel_code: ClassVar[str] = "publicbank"
    timeout_seconds: ClassVar[int] = 20
    URL: ClassVar[str] = "https://www.pbebank.com/en/rates-charges/forex/"

    async def fetch(self, base: str, quote: str) -> ScrapeResult:
        if quote != "MYR":
            raise ScraperError(f"publicbank: only MYR quote is supported (got {quote})")
        if base != "CNY":
            raise ScraperError(f"publicbank: only CNY base is configured (got {base})")
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
                        "publicbank: HTTP 403 from server-side GET — likely a WAF block. "
                        "Plain GET worked when this scraper was authored; if this "
                        "starts firing the channel may need the same Playwright "
                        "treatment Maybank got (and that ultimately failed)."
                    )
                resp.raise_for_status()
                return resp.text
        except httpx.HTTPError as exc:
            raise ScraperError(f"publicbank: HTTP error: {exc}") from exc

    # ---- pure parser --------------------------------------------------

    def _parse(self, html: str, *, base: str, quote: str) -> ScrapeResult:
        if PAGE_MARKER not in html:
            raise ScraperError(
                f"publicbank: response missing marker {PAGE_MARKER!r} — "
                "either the page structure changed or we got a WAF page."
            )

        soup = BeautifulSoup(html, "lxml")
        table = self._find_forex_table(soup)
        if table is None:
            raise ScraperError(f"publicbank: no <table> containing {ROW_NEEDLE!r} found on page")

        header_idx = self._buying_tt_column_index(table)
        if header_idx is None:
            raise ScraperError(
                f"publicbank: no {COLUMN_HEADER_BUYING_TT!r} header column in forex table"
            )

        row = self._find_cny_row(table)
        if row is None:
            raise ScraperError(f"publicbank: no row matching {ROW_NEEDLE!r} in forex table")

        label, cells = row
        multiplier = self._extract_multiplier(label)
        if multiplier is None:
            raise ScraperError(f"publicbank: cannot extract multiplier from row label {label!r}")

        # header_idx is the 0-based column index across ALL header cells
        # (including the leading 'Currency' header). Within the data row,
        # cells[0] is the label cell — so the rate cell index shifts by 1.
        rate_idx = header_idx - 1
        if rate_idx < 0 or rate_idx >= len(cells):
            raise ScraperError(
                f"publicbank: Buying TT column index {header_idx} out of range "
                f"({len(cells)} rate cells in CNY row)"
            )
        buying_tt_raw = cells[rate_idx]
        if buying_tt_raw is None:
            raise ScraperError(
                f"publicbank: Buying TT cell is N/A for {ROW_NEEDLE!r}; " "cannot compute rate"
            )

        try:
            buying_tt = Decimal(str(buying_tt_raw))
        except Exception as exc:
            raise ScraperError(
                f"publicbank: cannot parse Buying TT {buying_tt_raw!r}: {exc}"
            ) from exc

        rate = (buying_tt / Decimal(multiplier)).quantize(Decimal("0.00000001"))
        self._sanity_check(rate)

        return ScrapeResult(
            base_currency=base,
            quote_currency=quote,
            rate=rate,
            rate_type="tt_buy",
            raw_payload={
                "row_label": label,
                "multiplier": multiplier,
                "buying_tt": buying_tt_raw,
                "all_rate_cells": cells,
                "last_updated": self._extract_last_updated(html),
            },
            fee_estimate=None,
            fee_currency=None,
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
    def _buying_tt_column_index(table: Tag) -> int | None:
        """Return the 0-based column index of the 'Buying TT' header cell
        within the first row that looks like the forex header. We require
        the header row to contain BOTH 'Currency' and 'Buying TT' as exact
        cell texts — this prevents accidentally matching a stray 'Buying TT'
        in a footnote and rejects the 'Currency Notes Selling' false match."""
        for tr in table.find_all("tr"):
            if not isinstance(tr, Tag):
                continue
            headers = tr.find_all(["th", "td"])
            texts = [h.get_text(" ", strip=True) for h in headers]
            if COLUMN_HEADER_BUYING_TT in texts and COLUMN_HEADER_CURRENCY in texts:
                return texts.index(COLUMN_HEADER_BUYING_TT)
        return None

    @staticmethod
    def _find_cny_row(table: Tag) -> tuple[str, list[str | None]] | None:
        """Return (row_label, [rate_cells_without_label]) for the first <tr>
        whose first <td> contains 'Chinese Renminbi'. N/A cells become None.
        Returns None if no such row exists."""
        for tr in table.find_all("tr"):
            if not isinstance(tr, Tag):
                continue
            cells = tr.find_all("td")
            if not cells:
                continue
            label = cells[0].get_text(" ", strip=True)
            if ROW_NEEDLE not in label:
                continue
            rate_cells: list[str | None] = []
            for c in cells[1:]:
                txt = c.get_text(" ", strip=True)
                if not txt or txt.upper() == "N/A":
                    rate_cells.append(None)
                else:
                    rate_cells.append(txt)
            return label, rate_cells
        return None

    @staticmethod
    def _extract_multiplier(label: str) -> int | None:
        """Parse the leading integer from a row label like '100 Chinese
        Renminbi (Non Trade)'. Labels with no leading integer (e.g.
        '1 Australian Dollar') are also valid — multiplier = 1."""
        m = re.match(r"\s*(\d+)\s+Chinese Renminbi", label, re.IGNORECASE)
        if not m:
            return None
        try:
            v = int(m.group(1))
            return v if v > 0 else None
        except ValueError:
            return None

    @staticmethod
    def _extract_last_updated(html: str) -> str | None:
        """Best-effort scrape of the 'Foreign Exchange Rate as at <ts>'
        paragraph that appears just above the rates table."""
        m = re.search(
            r"Foreign\s+Exchange\s+Rate\s*(?:s)?\s+as\s+at\s+([0-9A-Za-z\s:,]+?)(?:</|<br)",
            html,
            re.IGNORECASE,
        )
        return m.group(1).strip() if m else None
