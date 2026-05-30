from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import ClassVar

import httpx
from bs4 import BeautifulSoup, Tag

from app.scrapers.base import Scraper, ScraperError, ScrapeResult

# Standard Chartered Malaysia. The forex board is embedded on the
# (oddly-named) deposits/interest-rates page as one of ~17 server-rendered
# tables. Plain GET + project UA returns 200 with the full table (the page
# also references Imperva/Incapsula scripts, but they do NOT block — verified
# 2026-05-30: HTTP 200, rates inline). No proxy / curl_cffi needed.
PROJECT_HEADERS: dict[str, str] = {
    "User-Agent": "rate.005917.xyz contact: lixuwei2005@gmail.com",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

ROW_NEEDLE = "CHINESE RENMINBI"
# Header labels arrive whitespace-collapsed (e.g. "BUYINGTT"); we match on a
# space-stripped, upper-cased form so "BUYING TT" / "Buying TT" also work.
KEY_BUY_TT = "BUYINGTT"
KEY_UNIT = "UNIT"
# Structural marker for the forex board specifically (the page has many other
# rate tables). Absent → page changed / blocked.
PAGE_MARKER = ROW_NEEDLE
_UNAVAILABLE = {"", "-", "--", "N/A", "NA", "0"}


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s).upper()


class StandardCharteredScraper(Scraper):
    """Standard Chartered Bank (Malaysia) foreign-exchange board.

    URL: https://www.sc.com/my/deposits/interest-rates/  (the FX table lives
    on this page despite the deposits-y URL.)

    The relevant ``<table>`` header is:

        UNIT | CURRENCY | SELLING TT/OD | BUYINGTT | BUYINGCP | SWIFT CODE

    Header and data rows share column count, so a header-label lookup maps
    straight to the data cell. Rates are MYR per `UNIT` foreign units (100 for
    CNY). For CNY → MYR the customer hands CNY to the bank and gets MYR — the
    bank BUYS CNY — so we use **BUYINGTT** ÷ UNIT. 'BUYINGCP' (cash) is 0/NA
    for CNY and ignored.

    Fee model: fee_estimate is None — the spread is already in BUYINGTT.
    """

    channel_code: ClassVar[str] = "sc"
    timeout_seconds: ClassVar[int] = 20
    URL: ClassVar[str] = "https://www.sc.com/my/deposits/interest-rates/"

    async def fetch(self, base: str, quote: str) -> ScrapeResult:
        if quote != "MYR":
            raise ScraperError(f"sc: only MYR quote is configured (got {quote})")
        if base != "CNY":
            raise ScraperError(f"sc: only CNY base is configured (got {base})")
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
                        "sc: HTTP 403 from server-side GET — likely a WAF block. "
                        "Plain GET worked when this scraper was authored."
                    )
                resp.raise_for_status()
                return resp.text
        except httpx.HTTPError as exc:
            raise ScraperError(f"sc: HTTP error: {exc}") from exc

    # ---- pure parser --------------------------------------------------

    def _parse(self, html: str, *, base: str, quote: str) -> ScrapeResult:
        if PAGE_MARKER not in html.upper():
            raise ScraperError(
                f"sc: response missing marker {PAGE_MARKER!r} — page changed or WAF page."
            )

        soup = BeautifulSoup(html, "lxml")
        table, header = self._find_fx_table(soup)
        if table is None or header is None:
            raise ScraperError(
                f"sc: no <table> with a header containing {KEY_BUY_TT!r} + {KEY_UNIT!r}"
            )

        norm = [_norm(h) for h in header]
        try:
            i_buytt = norm.index(KEY_BUY_TT)
            i_unit = norm.index(KEY_UNIT)
        except ValueError as exc:
            raise ScraperError(f"sc: required header column missing: {exc}") from exc

        row = self._find_cny_row(table)
        if row is None:
            raise ScraperError(f"sc: no row containing {ROW_NEEDLE!r} in the forex table")
        if len(row) != len(header):
            raise ScraperError(
                f"sc: CNY row has {len(row)} cells, expected {len(header)} (header mismatch)"
            )

        buytt_raw = row[i_buytt]
        unit_raw = row[i_unit]
        if buytt_raw is None or buytt_raw.upper() in _UNAVAILABLE:
            raise ScraperError(f"sc: {KEY_BUY_TT} is unavailable ({buytt_raw!r}) for CNY")
        try:
            buytt = Decimal(buytt_raw.replace(",", ""))
            unit = Decimal((unit_raw or "").replace(",", ""))
        except InvalidOperation as exc:
            raise ScraperError(
                f"sc: cannot parse BUYINGTT {buytt_raw!r} / UNIT {unit_raw!r}: {exc}"
            ) from exc
        if unit <= 0:
            raise ScraperError(f"sc: non-positive UNIT {unit_raw!r}")
        if buytt <= 0:
            raise ScraperError(f"sc: BUYINGTT is {buytt_raw!r} (zero) for CNY")

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
                "unit": unit_raw,
                "selling_tt_od": (
                    row[norm.index("SELLINGTT/OD")] if "SELLINGTT/OD" in norm else None
                ),
                "buying_cp": row[norm.index("BUYINGCP")] if "BUYINGCP" in norm else None,
            },
            fee_estimate=None,
            fee_currency=None,
        )

    # ---- helpers ------------------------------------------------------

    @staticmethod
    def _find_fx_table(soup: BeautifulSoup) -> tuple[Tag | None, list[str] | None]:
        """The FX table among many: header has BUYINGTT + UNIT and the body
        mentions CHINESE RENMINBI."""
        for t in soup.find_all("table"):
            if not isinstance(t, Tag):
                continue
            if ROW_NEEDLE not in t.get_text(" ", strip=True).upper():
                continue
            for tr in t.find_all("tr"):
                cells = [_norm(c.get_text(" ", strip=True)) for c in tr.find_all(["th", "td"])]
                if KEY_BUY_TT in cells and KEY_UNIT in cells:
                    raw = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
                    return t, raw
        return None, None

    @staticmethod
    def _find_cny_row(table: Tag) -> list[str | None] | None:
        for tr in table.find_all("tr"):
            if not isinstance(tr, Tag):
                continue
            cells = tr.find_all(["th", "td"])
            if not cells:
                continue
            texts = [c.get_text(" ", strip=True) for c in cells]
            if ROW_NEEDLE not in " ".join(texts).upper():
                continue
            # Skip a header row that happens to mention the needle.
            if KEY_BUY_TT in [_norm(t) for t in texts]:
                continue
            return [
                None if (not t or t.upper() in {"", "-", "--", "N/A", "NA"}) else t for t in texts
            ]
        return None
