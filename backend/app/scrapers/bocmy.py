from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import ClassVar

import httpx
from bs4 import BeautifulSoup, Tag

from app.scrapers.base import Scraper, ScraperError, ScrapeResult

# Bank of China (Malaysia) Berhad — DISTINCT from the `boc` channel, which
# scrapes boc.cn (Bank of China in mainland China, 现汇卖出价). This is the
# Malaysian entity quoting MYR directly. Server-rendered HTML, plain GET +
# project UA returns 200, no bot wall (verified 2026-05-30).
#
# The header cells are bilingual and <br/>-split, e.g.
#   <td>买入价<br/>We Buy<br/>TT</td>
# so the literal "We Buy TT" is NOT contiguous in the raw HTML — we must
# extract cell text (BeautifulSoup joins the <br/> fragments with a space)
# before matching. We then match on the ASCII half (space-stripped) so the
# Chinese label doesn't matter. The page is UTF-8 despite earlier confusion.
PROJECT_HEADERS: dict[str, str] = {
    "User-Agent": "rate.005917.xyz contact: lixuwei2005@gmail.com",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

ROW_CODE = "CNY"
KEY_BUY_TT = "WEBUYTT"  # space-stripped form; matched as a substring of a cell
KEY_SELL_TT = "WESELLTT"
# The board is uniformly quoted per 100 foreign units (Malaysian-bank
# convention; confirmed by JPY 2.44 / CNY 57.61 only making sense ÷100). The
# UNIT column header exists but the CNY cell carries the code, not a number,
# so we fix the multiplier rather than read it.
# TODO recheck-2026-11: confirm the board is still per-100 (watch JPY's magnitude).
MULTIPLIER = 100
# Marker checked AFTER BeautifulSoup extracts cell text — in the raw HTML the
# header is <br/>-split (买入价<br/>We Buy<br/>TT) so "We Buy TT" isn't literal.
PAGE_MARKER = "WEBUYTT"
_UNAVAILABLE = {"", "-", "--", "N/A", "NA"}


def _norm(s: str) -> str:
    return "".join(s.split()).upper()


class BOCMalaysiaScraper(Scraper):
    """Bank of China (Malaysia) foreign-exchange board.

    URL: https://www.bankofchina.com/sourcedb/myr/

    One server-rendered table. Header (English half is ASCII):

        UNIT | Currency | We Buy TT | We Sell TT | We Buy Cash | We Sell Cash | Update Time

    Rates are MYR per 100 foreign units. For CNY → MYR the customer hands CNY
    to the bank and gets MYR — the bank BUYS CNY — so we use **We Buy TT** ÷ 100.
    Cash columns are ignored. The CNY row is located by its ASCII code cell.

    Fee model: fee_estimate is None — the spread is already in We Buy TT.
    """

    channel_code: ClassVar[str] = "bocmy"
    timeout_seconds: ClassVar[int] = 20
    URL: ClassVar[str] = "https://www.bankofchina.com/sourcedb/myr/"

    async def fetch(self, base: str, quote: str) -> ScrapeResult:
        if quote != "MYR":
            raise ScraperError(f"bocmy: only MYR quote is configured (got {quote})")
        if base != "CNY":
            raise ScraperError(f"bocmy: only CNY base is configured (got {base})")
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
                        "bocmy: HTTP 403 from server-side GET — likely a WAF block. "
                        "Plain GET worked when this scraper was authored."
                    )
                resp.raise_for_status()
                # Page is UTF-8 (httpx detects it). We match on the ASCII half
                # of each bilingual cell, so the exact decode of the Chinese
                # names doesn't affect parsing.
                return resp.text
        except httpx.HTTPError as exc:
            raise ScraperError(f"bocmy: HTTP error: {exc}") from exc

    # ---- pure parser --------------------------------------------------

    def _parse(self, html: str, *, base: str, quote: str) -> ScrapeResult:
        soup = BeautifulSoup(html, "lxml")
        table, header = self._find_fx_table(soup)
        if table is None or header is None:
            raise ScraperError(
                f"bocmy: no <table> with a header containing {PAGE_MARKER!r} "
                "(missing marker) — page changed or WAF page."
            )

        # Substring match: header cell is "买入价 We Buy TT" → norm "买入价WEBUYTT".
        norm = [_norm(h) for h in header]
        i_buytt = next((i for i, h in enumerate(norm) if KEY_BUY_TT in h), None)
        if i_buytt is None:
            raise ScraperError("bocmy: 'We Buy TT' column missing")
        i_selltt = next((i for i, h in enumerate(norm) if KEY_SELL_TT in h), None)

        row = self._find_cny_row(table)
        if row is None:
            raise ScraperError(f"bocmy: no row for currency code {ROW_CODE!r} in the board")
        if i_buytt >= len(row):
            raise ScraperError(
                f"bocmy: CNY row has {len(row)} cells, no index {i_buytt} for We Buy TT"
            )

        buytt_raw = row[i_buytt]
        if buytt_raw is None or buytt_raw.upper() in _UNAVAILABLE:
            raise ScraperError(f"bocmy: We Buy TT is unavailable ({buytt_raw!r}) for CNY")
        try:
            buytt = Decimal(buytt_raw.replace(",", ""))
        except InvalidOperation as exc:
            raise ScraperError(f"bocmy: cannot parse We Buy TT {buytt_raw!r}: {exc}") from exc
        if buytt <= 0:
            raise ScraperError(f"bocmy: We Buy TT is {buytt_raw!r} (zero) for CNY")

        rate = (buytt / Decimal(MULTIPLIER)).quantize(Decimal("0.00000001"))
        if base == "CNY" and quote == "MYR":
            self._sanity_check(rate)

        return ScrapeResult(
            base_currency=base,
            quote_currency=quote,
            rate=rate,
            rate_type="tt_buy",
            raw_payload={
                "we_buy_tt": buytt_raw,
                "multiplier": MULTIPLIER,
                "we_sell_tt": (
                    row[i_selltt] if i_selltt is not None and i_selltt < len(row) else None
                ),
                "update_time": row[-1] if row else None,
            },
            fee_estimate=None,
            fee_currency=None,
        )

    # ---- helpers ------------------------------------------------------

    @staticmethod
    def _find_fx_table(soup: BeautifulSoup) -> tuple[Tag | None, list[str] | None]:
        """Find the table whose header has a cell containing "We Buy TT".
        Cells are bilingual ("买入价 We Buy TT") so we substring-match the
        space-stripped ASCII key, not exact-equal."""
        for t in soup.find_all("table"):
            if not isinstance(t, Tag):
                continue
            for tr in t.find_all("tr"):
                raw = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
                if any(KEY_BUY_TT in _norm(c) for c in raw):
                    return t, raw
        return None, None

    @staticmethod
    def _find_cny_row(table: Tag) -> list[str | None] | None:
        """Row whose first cell's ISO code == ROW_CODE (ASCII; ignores the
        garbled Chinese name cell)."""
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
