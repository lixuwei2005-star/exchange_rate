from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import ClassVar

import httpx
from bs4 import BeautifulSoup, Tag

from app.scrapers.base import Scraper, ScraperError, ScrapeResult

# Alliance Bank Malaysia's forex kiosk page is server-rendered HTML reachable
# with a plain GET using the project User-Agent (verified 2026-05-29: HTTP 200,
# rates inline, no Cloudflare JS challenge). An F5 BIG-IP ASM WAF (TS* cookies)
# fronts the host but served a plain server-side GET fine — flagged as a
# fragility risk in CLAUDE.md §6 (it could start challenging data-centre IPs,
# the way Akamai blocked Maybank from OCI). # TODO recheck-2026-11
PROJECT_HEADERS: dict[str, str] = {
    "User-Agent": "rate.005917.xyz contact: lixuwei2005@gmail.com",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

ROW_NEEDLE = "CHINESE RENMINBI"
COLUMN_HEADER_BUY_TT = "Buying TT"
COLUMN_HEADER_PER_UNIT = "Per Unit"
# Structural presence marker: the rates table's id. Absent → we got an
# error/interstitial/WAF page or the markup changed, not the live board.
PAGE_MARKER = "forexList"
_UNAVAILABLE = {"", "-", "--", "N/A", "NA"}


class AllianceScraper(Scraper):
    """Alliance Bank Malaysia forex kiosk rates page.

    URL: https://www.allianceonline.com.my/personal/rate_charges/
         foreign_exchange_rate_kiosk_view.do

    Server-renders one ``<table id="forexList">``. Header row:

        Foreign Currency | Country | Per Unit | Selling TT | Selling Cash
        | Buying TT | Buying OD | Buying Cash

    The header and the data rows have the SAME column count (the currency
    code + name share the first 'Foreign Currency' cell), so a header-label
    lookup maps straight to the same index in the data row — no offset, unlike
    RHB.

    For CNY → MYR the customer hands CNY to the bank and gets MYR — the bank
    BUYS CNY — so we use the **Buying TT** column (telegraphic transfer,
    electronic), divided by the row's Per Unit (100 for CNY). 'Cash' and 'OD'
    columns are ignored, same policy as the other banks.

    Fee model: fee_estimate is None — the bank spread is already in Buying TT.
    """

    channel_code: ClassVar[str] = "alliance"
    timeout_seconds: ClassVar[int] = 20
    URL: ClassVar[str] = (
        "https://www.allianceonline.com.my/personal/rate_charges/"
        "foreign_exchange_rate_kiosk_view.do"
    )

    async def fetch(self, base: str, quote: str) -> ScrapeResult:
        if quote != "MYR":
            raise ScraperError(f"alliance: only MYR quote is configured (got {quote})")
        if base != "CNY":
            raise ScraperError(f"alliance: only CNY base is configured (got {base})")
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
                        "alliance: HTTP 403 from server-side GET — likely a WAF block. "
                        "Plain GET worked when this scraper was authored."
                    )
                resp.raise_for_status()
                return resp.text
        except httpx.HTTPError as exc:
            raise ScraperError(f"alliance: HTTP error: {exc}") from exc

    # ---- pure parser --------------------------------------------------

    def _parse(self, html: str, *, base: str, quote: str) -> ScrapeResult:
        if PAGE_MARKER not in html:
            raise ScraperError(
                f"alliance: response missing marker {PAGE_MARKER!r} — page changed or WAF page."
            )

        soup = BeautifulSoup(html, "lxml")
        table = self._find_forex_table(soup)
        if table is None:
            raise ScraperError(f"alliance: no <table> containing {ROW_NEEDLE!r} found on page")

        header = self._find_header(table)
        if header is None:
            raise ScraperError(
                f"alliance: no header row with {COLUMN_HEADER_BUY_TT!r} + "
                f"{COLUMN_HEADER_PER_UNIT!r} found"
            )

        try:
            i_buytt = header.index(COLUMN_HEADER_BUY_TT)
            i_unit = header.index(COLUMN_HEADER_PER_UNIT)
        except ValueError as exc:
            raise ScraperError(f"alliance: required header column missing: {exc}") from exc

        row = self._find_cny_row(table)
        if row is None:
            raise ScraperError(f"alliance: no row containing {ROW_NEEDLE!r} in forex table")
        if len(row) != len(header):
            raise ScraperError(
                f"alliance: CNY row has {len(row)} cells, expected {len(header)} (header mismatch)"
            )

        buytt_raw = row[i_buytt]
        unit_raw = row[i_unit]
        if buytt_raw is None or buytt_raw.upper() in _UNAVAILABLE:
            raise ScraperError(f"alliance: {COLUMN_HEADER_BUY_TT} is unavailable ({buytt_raw!r})")

        try:
            buytt = Decimal(buytt_raw.replace(",", ""))
            unit = Decimal(unit_raw.replace(",", ""))
        except InvalidOperation as exc:
            raise ScraperError(
                f"alliance: cannot parse {COLUMN_HEADER_BUY_TT} {buytt_raw!r} / "
                f"{COLUMN_HEADER_PER_UNIT} {unit_raw!r}: {exc}"
            ) from exc
        if unit <= 0:
            raise ScraperError(f"alliance: non-positive Per Unit {unit}")
        if buytt <= 0:
            raise ScraperError(
                f"alliance: {COLUMN_HEADER_BUY_TT} is {buytt_raw!r} (zero/unavailable) for CNY"
            )

        rate = (buytt / unit).quantize(Decimal("0.00000001"))
        if base == "CNY" and quote == "MYR":
            self._sanity_check(rate)

        return ScrapeResult(
            base_currency=base,
            quote_currency=quote,
            rate=rate,
            rate_type="tt_buy",
            raw_payload={
                "buying_tt": buytt_raw,
                "per_unit": unit_raw,
                "selling_tt": row[header.index("Selling TT")] if "Selling TT" in header else None,
                "buying_od": row[header.index("Buying OD")] if "Buying OD" in header else None,
            },
            fee_estimate=None,
            fee_currency=None,
        )

    # ---- helpers ------------------------------------------------------

    @staticmethod
    def _find_forex_table(soup: BeautifulSoup) -> Tag | None:
        by_id = soup.find("table", id=PAGE_MARKER)
        if isinstance(by_id, Tag):
            return by_id
        for t in soup.find_all("table"):
            if isinstance(t, Tag) and ROW_NEEDLE in t.get_text(" ", strip=True).upper():
                return t
        return None

    @staticmethod
    def _find_header(table: Tag) -> list[str] | None:
        for tr in table.find_all("tr"):
            if not isinstance(tr, Tag):
                continue
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
            if COLUMN_HEADER_BUY_TT in cells and COLUMN_HEADER_PER_UNIT in cells:
                return cells
        return None

    @staticmethod
    def _find_cny_row(table: Tag) -> list[str | None] | None:
        """Return the data row containing 'CHINESE RENMINBI'. N/A-ish cells
        become None. None if no such row."""
        for tr in table.find_all("tr"):
            if not isinstance(tr, Tag):
                continue
            cells = tr.find_all(["th", "td"])
            if not cells:
                continue
            texts = [c.get_text(" ", strip=True) for c in cells]
            if ROW_NEEDLE not in " ".join(texts).upper():
                continue
            # Skip the header row (it has no rate digits, only labels).
            if COLUMN_HEADER_BUY_TT in texts:
                continue
            return [None if (not t or t.upper() in _UNAVAILABLE) else t for t in texts]
        return None
