from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import ClassVar

import httpx
from bs4 import BeautifulSoup, Tag

from app.scrapers.base import Scraper, ScraperError, ScrapeResult

# Hong Leong Bank Malaysia publishes its forex board as server-rendered HTML.
# Verified 2026-05-29: a plain GET with the project User-Agent returns HTTP 200
# with the rate values inline — no Cloudflare/Akamai bot wall, no JS rendering.
# # TODO recheck-2026-11
PROJECT_HEADERS: dict[str, str] = {
    "User-Agent": "rate.005917.xyz contact: lixuwei2005@gmail.com",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# The CNY row's name cell reads "CHINESE RENMINBI (CNY)".
ROW_NEEDLE = "CHINESE RENMINBI"
# CNY → MYR: the customer hands CNY to the bank and gets MYR, so the bank BUYS
# CNY → telegraphic-transfer buy rate. The same row also carries a "Buying
# (OD/TC)" cell and a preferential-account "Buying" cell, so we match the TT
# label EXACTLY rather than just "Buying".
BUY_TT_LABEL = "Buying (TT)"
SELL_LABEL = "Selling (TT/OD/TC)"
BUY_OD_LABEL = "Buying (OD/TC)"
# Structural presence marker: the rates table's cell class. Absent → we got an
# error/interstitial page or the markup changed, not the live board.
PAGE_MARKER = "forex-rates-table-data"
# Row basis label e.g. "RINGGIT TO 100 UNITS OF FOREIGN CURRENCY" → divisor 100.
MULTIPLIER_RE = re.compile(r"RINGGIT\s+TO\s+([\d,]+)\s+UNIT", re.IGNORECASE)
_UNAVAILABLE = {"", "-", "--", "N/A", "NA"}


class HLBScraper(Scraper):
    """Hong Leong Bank Malaysia forex board.

    URL: https://www.hlb.com.my/en/global-markets/forex-rates.html

    Server-renders one forex table. Unlike a classic header+rows table, each
    cell is self-labelling — a ``<td>`` holds::

        <div class="left-col">LABEL</div><div class="right-col">VALUE</div>

    so we locate values by their LABEL, not by column position. The CNY row's
    name cell carries the per-unit basis ("RINGGIT TO 100 UNITS OF FOREIGN
    CURRENCY") which gives the divisor.

    For CNY → MYR the customer hands CNY to the bank and gets MYR — the bank
    BUYS CNY — so we use the **Buying (TT)** value (telegraphic transfer,
    electronic), divided by the row multiplier (100 for CNY). The "OD/TC" and
    preferential-account columns are ignored, same policy as the other banks.

    Fee model: fee_estimate is None — the bank spread is already in Buying (TT).
    """

    channel_code: ClassVar[str] = "hlb"
    timeout_seconds: ClassVar[int] = 20
    URL: ClassVar[str] = "https://www.hlb.com.my/en/global-markets/forex-rates.html"

    async def fetch(self, base: str, quote: str) -> ScrapeResult:
        if quote != "MYR":
            raise ScraperError(f"hlb: only MYR quote is configured (got {quote})")
        if base != "CNY":
            raise ScraperError(f"hlb: only CNY base is configured (got {base})")
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
                        "hlb: HTTP 403 from server-side GET — likely a WAF block. "
                        "Plain GET worked when this scraper was authored."
                    )
                resp.raise_for_status()
                return resp.text
        except httpx.HTTPError as exc:
            raise ScraperError(f"hlb: HTTP error: {exc}") from exc

    # ---- pure parser --------------------------------------------------

    def _parse(self, html: str, *, base: str, quote: str) -> ScrapeResult:
        if PAGE_MARKER not in html:
            raise ScraperError(
                f"hlb: response missing marker {PAGE_MARKER!r} — page changed or WAF page."
            )

        soup = BeautifulSoup(html, "lxml")
        row = self._find_cny_row(soup)
        if row is None:
            raise ScraperError(f"hlb: no row containing {ROW_NEEDLE!r} found on page")

        multiplier = self._extract_multiplier(row)
        buy_tt_raw = self._labeled_value(row, BUY_TT_LABEL)
        if buy_tt_raw is None or buy_tt_raw.upper() in _UNAVAILABLE:
            raise ScraperError(
                f"hlb: {BUY_TT_LABEL!r} is unavailable ({buy_tt_raw!r}) for CNY; cannot compute rate"
            )

        try:
            buy_tt = Decimal(buy_tt_raw.replace(",", ""))
        except InvalidOperation as exc:
            raise ScraperError(f"hlb: cannot parse {BUY_TT_LABEL} {buy_tt_raw!r}: {exc}") from exc

        rate = (buy_tt / multiplier).quantize(Decimal("0.00000001"))
        if base == "CNY" and quote == "MYR":
            self._sanity_check(rate)

        return ScrapeResult(
            base_currency=base,
            quote_currency=quote,
            rate=rate,
            rate_type="tt_buy",
            raw_payload={
                "buying_tt": buy_tt_raw,
                "selling": self._labeled_value(row, SELL_LABEL),
                "buying_od_tc": self._labeled_value(row, BUY_OD_LABEL),
                "multiplier": str(multiplier),
            },
            fee_estimate=None,
            fee_currency=None,
        )

    # ---- helpers ------------------------------------------------------

    @staticmethod
    def _find_cny_row(soup: BeautifulSoup) -> Tag | None:
        for tr in soup.find_all("tr"):
            if not isinstance(tr, Tag):
                continue
            if ROW_NEEDLE in tr.get_text(" ", strip=True).upper():
                return tr
        return None

    @staticmethod
    def _extract_multiplier(row: Tag) -> Decimal:
        m = MULTIPLIER_RE.search(row.get_text(" ", strip=True))
        if not m:
            raise ScraperError("hlb: could not find 'RINGGIT TO N UNITS' basis in CNY row")
        try:
            value = Decimal(m.group(1).replace(",", ""))
        except InvalidOperation as exc:
            raise ScraperError(f"hlb: bad multiplier {m.group(1)!r}: {exc}") from exc
        if value <= 0:
            raise ScraperError(f"hlb: non-positive multiplier {value}")
        return value

    @staticmethod
    def _labeled_value(row: Tag, label: str) -> str | None:
        """Within a row, find the <td> whose .left-col text == label and return
        its .right-col text. None if there's no such labelled cell."""
        for td in row.find_all("td"):
            if not isinstance(td, Tag):
                continue
            lc = td.find("div", class_="left-col")
            if lc is None or lc.get_text(" ", strip=True) != label:
                continue
            rc = td.find("div", class_="right-col")
            return rc.get_text(" ", strip=True) if rc is not None else None
        return None
