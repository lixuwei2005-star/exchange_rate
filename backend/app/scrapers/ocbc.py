from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import ClassVar

import httpx
from bs4 import BeautifulSoup, Tag

from app.scrapers.base import Scraper, ScraperError, ScrapeResult

# OCBC Malaysia. The public www.ocbc.com.my page is an Incapsula-protected
# shell (JS bot wall) — but the actual board lives on the internet-banking
# PUBLIC host, which server-renders a plain HTML table reachable with a plain
# GET + the project UA (verified 2026-05-30: HTTP 200, no Incapsula, rates
# inline). No proxy / curl_cffi needed.
PROJECT_HEADERS: dict[str, str] = {
    "User-Agent": "rate.005917.xyz contact: lixuwei2005@gmail.com",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

COLUMN_HEADER_BUY_TT = "Buy TT"
COLUMN_HEADER_UNIT = "Unit"
# Structural marker: the rate table's Buy-TT header. Absent → WAF/error page
# or the markup changed, not the live board.
PAGE_MARKER = COLUMN_HEADER_BUY_TT
# Onshore CNY. The board also lists a CNH (offshore) row with the same name
# "CHINESE YUAN"; we must key on the CODE, not the name, to avoid picking it.
ROW_CODE = "CNY"
_UNAVAILABLE = {"", "-", "--", "N/A", "NA"}


class OCBCScraper(Scraper):
    """OCBC Bank (Malaysia) TT/OD foreign-exchange board.

    URL: https://internet.ocbc.com.my/ocbc-public/ForeignExchangeTTODPublic/Index

    Server-renders one ``<table>``. Header row:

        Currency | Unit | Sell TT/OD | Buy TT | Buy OD

    Each data row's first cell is "CODE  NAME" (e.g. "CNY  CHINESE YUAN");
    header and data rows have the SAME column count, so a header-label lookup
    maps straight to the same index in the data row. Rates are MYR per `Unit`
    foreign units (100 for CNY).

    For CNY → MYR the customer hands CNY to the bank and gets MYR — the bank
    BUYS CNY — so we use **Buy TT** ÷ Unit. 'Buy OD' and 'Sell TT/OD' are
    ignored. We pick the CNY (onshore) row, NOT CNH (offshore).

    Fee model: fee_estimate is None — the spread is already in Buy TT.
    """

    channel_code: ClassVar[str] = "ocbc"
    timeout_seconds: ClassVar[int] = 20
    URL: ClassVar[str] = "https://internet.ocbc.com.my/ocbc-public/ForeignExchangeTTODPublic/Index"

    async def fetch(self, base: str, quote: str) -> ScrapeResult:
        if quote != "MYR":
            raise ScraperError(f"ocbc: only MYR quote is configured (got {quote})")
        if base != "CNY":
            raise ScraperError(f"ocbc: only CNY base is configured (got {base})")
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
                        "ocbc: HTTP 403 from server-side GET — likely a WAF block. "
                        "Plain GET to the internet-banking public host worked when "
                        "this scraper was authored."
                    )
                resp.raise_for_status()
                return resp.text
        except httpx.HTTPError as exc:
            raise ScraperError(f"ocbc: HTTP error: {exc}") from exc

    # ---- pure parser --------------------------------------------------

    def _parse(self, html: str, *, base: str, quote: str) -> ScrapeResult:
        if PAGE_MARKER not in html:
            raise ScraperError(
                f"ocbc: response missing marker {PAGE_MARKER!r} — page changed or WAF page."
            )

        soup = BeautifulSoup(html, "lxml")
        table, header = self._find_table_and_header(soup)
        if table is None or header is None:
            raise ScraperError(
                f"ocbc: no <table> with a header containing "
                f"{COLUMN_HEADER_BUY_TT!r} + {COLUMN_HEADER_UNIT!r}"
            )

        try:
            i_buytt = header.index(COLUMN_HEADER_BUY_TT)
            i_unit = header.index(COLUMN_HEADER_UNIT)
        except ValueError as exc:
            raise ScraperError(f"ocbc: required header column missing: {exc}") from exc

        row = self._find_cny_row(table)
        if row is None:
            raise ScraperError(f"ocbc: no row for currency code {ROW_CODE!r} in board")
        if len(row) != len(header):
            raise ScraperError(
                f"ocbc: CNY row has {len(row)} cells, expected {len(header)} (header mismatch)"
            )

        buytt_raw = row[i_buytt]
        unit_raw = row[i_unit]
        if buytt_raw is None or buytt_raw.upper() in _UNAVAILABLE:
            raise ScraperError(
                f"ocbc: {COLUMN_HEADER_BUY_TT} is unavailable ({buytt_raw!r}) for CNY"
            )
        try:
            buytt = Decimal(buytt_raw.replace(",", ""))
            unit = Decimal((unit_raw or "").replace(",", ""))
        except InvalidOperation as exc:
            raise ScraperError(
                f"ocbc: cannot parse {COLUMN_HEADER_BUY_TT} {buytt_raw!r} / "
                f"{COLUMN_HEADER_UNIT} {unit_raw!r}: {exc}"
            ) from exc
        if unit <= 0:
            raise ScraperError(f"ocbc: non-positive Unit {unit_raw!r}")
        if buytt <= 0:
            raise ScraperError(f"ocbc: {COLUMN_HEADER_BUY_TT} is {buytt_raw!r} (zero) for CNY")

        rate = (buytt / unit).quantize(Decimal("0.00000001"))
        if base == "CNY" and quote == "MYR":
            self._sanity_check(rate)

        return ScrapeResult(
            base_currency=base,
            quote_currency=quote,
            rate=rate,
            rate_type="tt_buy",
            raw_payload={
                "buy_tt": buytt_raw,
                "unit": unit_raw,
                "sell_tt_od": row[header.index("Sell TT/OD")] if "Sell TT/OD" in header else None,
                "buy_od": row[header.index("Buy OD")] if "Buy OD" in header else None,
            },
            fee_estimate=None,
            fee_currency=None,
        )

    # ---- helpers ------------------------------------------------------

    @staticmethod
    def _find_table_and_header(soup: BeautifulSoup) -> tuple[Tag | None, list[str] | None]:
        for t in soup.find_all("table"):
            if not isinstance(t, Tag):
                continue
            for tr in t.find_all("tr"):
                cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
                if COLUMN_HEADER_BUY_TT in cells and COLUMN_HEADER_UNIT in cells:
                    return t, cells
        return None, None

    @staticmethod
    def _find_cny_row(table: Tag) -> list[str | None] | None:
        """Return the data row whose first cell's currency code == ROW_CODE.
        N/A-ish cells become None. Skips the CNH (offshore) row."""
        for tr in table.find_all("tr"):
            if not isinstance(tr, Tag):
                continue
            cells = tr.find_all(["th", "td"])
            if not cells:
                continue
            texts = [c.get_text(" ", strip=True) for c in cells]
            first = texts[0].replace("\xa0", " ").split()
            if not first or first[0].upper() != ROW_CODE:
                continue
            return [None if (not t or t.upper() in _UNAVAILABLE) else t for t in texts]
        return None
