from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import ClassVar

import httpx
from bs4 import BeautifulSoup, Tag

from app.scrapers._common import make_client, to_decimal
from app.scrapers.base import Scraper, ScraperError, ScrapeResult

# AmBank Malaysia's forex page is server-rendered HTML (a Sitefinity CMS content
# block — a Kendo-editor `<table class="k-table">`). Cloudflare fronts the host
# but only as a CDN cache (CF-Cache-Status HIT, no JS challenge); a plain GET
# with the project UA returns HTTP 200 (verified 2026-05-29). The board is
# manually maintained (~daily) and CDN-cached up to 12 h, so a modest poll
# cadence is plenty. # TODO recheck-2026-11
ROW_NEEDLE = "Chinese Renminbi"
COLUMN_HEADER_BUY_TT = "Buying TT"
COLUMN_HEADER_UNIT = "Currency Unit"
# Page-presence marker — the heading above the table. Absent → error/WAF page.
PAGE_MARKER = "Foreign Exchange Rates"
_UNAVAILABLE = {"", "-", "--", "N/A", "NA"}


class AmBankScraper(Scraper):
    """AmBank Malaysia foreign-exchange rates page.

    URL: https://www.ambank.com.my/rates-fees-charges/foreign-exchange-rates

    Server-renders one table. Header row (red background, plain ``<td>`` cells,
    first column is a flag image with an empty header):

        (flag) | Currency | Currency Unit | Selling TT / OD (RM)
        | Buying TT (RM) | Buying OD (RM)

    Header and data rows have the SAME column count, so a header-label lookup
    maps straight to the same index in the data row (no offset).

    For CNY → MYR the customer hands CNY to the bank and gets MYR — the bank
    BUYS CNY — so we use the **Buying TT** column divided by the row's Currency
    Unit (100 for CNY). 'OD' columns are ignored, same policy as the other
    banks.

    Fee model: fee_estimate is None — the spread is already in Buying TT.
    """

    channel_code: ClassVar[str] = "ambank"
    timeout_seconds: ClassVar[int] = 20
    URL: ClassVar[str] = "https://www.ambank.com.my/rates-fees-charges/foreign-exchange-rates"

    async def fetch(self, base: str, quote: str) -> ScrapeResult:
        if quote != "MYR":
            raise ScraperError(f"ambank: only MYR quote is configured (got {quote})")
        if base != "CNY":
            raise ScraperError(f"ambank: only CNY base is configured (got {base})")
        try:
            async with make_client(self.timeout_seconds) as client:
                resp = await client.get(self.URL)
                if resp.status_code == 403:
                    raise ScraperError(
                        "ambank: HTTP 403 — likely a Cloudflare challenge. "
                        "Plain GET worked when this scraper was authored."
                    )
                resp.raise_for_status()
                html = resp.text
        except httpx.HTTPError as exc:
            raise ScraperError(f"ambank: HTTP error: {exc}") from exc

        return self._parse(html, base=base, quote=quote)

    # ---- pure parser --------------------------------------------------

    def _parse(self, html: str, *, base: str, quote: str) -> ScrapeResult:
        if PAGE_MARKER not in html:
            raise ScraperError(
                f"ambank: response missing marker {PAGE_MARKER!r} — page changed or WAF page."
            )

        soup = BeautifulSoup(html, "lxml")
        table = self._find_forex_table(soup)
        if table is None:
            raise ScraperError(f"ambank: no <table> containing {ROW_NEEDLE!r} found on page")

        header = self._find_header(table)
        if header is None:
            raise ScraperError(
                f"ambank: no header row with {COLUMN_HEADER_BUY_TT!r} + {COLUMN_HEADER_UNIT!r}"
            )

        i_buytt = self._index_of(header, COLUMN_HEADER_BUY_TT)
        i_unit = self._index_of(header, COLUMN_HEADER_UNIT)
        if i_buytt is None or i_unit is None:
            raise ScraperError("ambank: required header column missing")

        row = self._find_cny_row(table)
        if row is None:
            raise ScraperError(f"ambank: no row containing {ROW_NEEDLE!r} in forex table")
        if max(i_buytt, i_unit) >= len(row):
            raise ScraperError(
                f"ambank: CNY row has {len(row)} cells, header expects index "
                f"{max(i_buytt, i_unit)} (header/row mismatch)"
            )

        buytt_raw = row[i_buytt]
        unit_raw = row[i_unit]
        if buytt_raw is None or buytt_raw.upper() in _UNAVAILABLE:
            raise ScraperError(f"ambank: {COLUMN_HEADER_BUY_TT} is unavailable ({buytt_raw!r})")

        try:
            buytt = to_decimal(buytt_raw)
            unit = to_decimal(unit_raw)
        except (InvalidOperation, ValueError) as exc:
            raise ScraperError(
                f"ambank: cannot parse Buying TT {buytt_raw!r} / Unit {unit_raw!r}: {exc}"
            ) from exc
        if unit <= 0:
            raise ScraperError(f"ambank: non-positive Currency Unit {unit}")
        if buytt <= 0:
            raise ScraperError(f"ambank: Buying TT is {buytt_raw!r} (zero/unavailable) for CNY")

        rate = (buytt / unit).quantize(Decimal("0.00000001"))
        if base == "CNY" and quote == "MYR":
            self._sanity_check(rate)

        def cell(needle: str) -> str | None:
            idx = self._index_of(header, needle)
            return row[idx] if idx is not None and idx < len(row) else None

        return ScrapeResult(
            base_currency=base,
            quote_currency=quote,
            rate=rate,
            rate_type="tt_buy",
            raw_payload={
                "buying_tt": buytt_raw,
                "currency_unit": unit_raw,
                "selling_tt_od": cell("Selling TT"),
                "buying_od": cell("Buying OD"),
            },
            fee_estimate=None,
            fee_currency=None,
        )

    # ---- helpers ------------------------------------------------------

    @staticmethod
    def _index_of(cells: list[str], needle: str) -> int | None:
        for i, c in enumerate(cells):
            if needle in c:
                return i
        return None

    @staticmethod
    def _find_forex_table(soup: BeautifulSoup) -> Tag | None:
        for t in soup.find_all("table"):
            if isinstance(t, Tag) and ROW_NEEDLE in t.get_text(" ", strip=True):
                return t
        return None

    @staticmethod
    def _find_header(table: Tag) -> list[str] | None:
        for tr in table.find_all("tr"):
            if not isinstance(tr, Tag):
                continue
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
            if any(COLUMN_HEADER_BUY_TT in c for c in cells) and any(
                COLUMN_HEADER_UNIT in c for c in cells
            ):
                return cells
        return None

    @staticmethod
    def _find_cny_row(table: Tag) -> list[str | None] | None:
        """Return the data row containing 'Chinese Renminbi' (not the header).
        N/A-ish cells become None."""
        for tr in table.find_all("tr"):
            if not isinstance(tr, Tag):
                continue
            cells = tr.find_all(["th", "td"])
            if not cells:
                continue
            texts = [c.get_text(" ", strip=True) for c in cells]
            joined = " ".join(texts)
            if ROW_NEEDLE not in joined:
                continue
            if COLUMN_HEADER_BUY_TT in joined:  # skip the header row
                continue
            return [None if (not t or t.upper() in _UNAVAILABLE) else t for t in texts]
        return None
