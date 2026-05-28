from __future__ import annotations

import re
from decimal import Decimal
from typing import ClassVar

import httpx
from bs4 import BeautifulSoup, Tag

from app.scrapers.base import Scraper, ScraperError, ScrapeResult

# Browser-like headers: Maybank sits behind Akamai. A plain GET with realistic
# desktop User-Agent + standard Accept headers works in some regions; if
# Akamai serves a challenge page instead, we detect that by the absence of
# the rate-table marker and raise — we do NOT rotate UAs or fake cookies.
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

# Page-presence marker. The HTML must contain this string anywhere; if not,
# treat as an Akamai/WAF interstitial and bail. Cheaper than parsing junk.
PAGE_MARKER = "Chinese Renminbi"

# Columns AFTER the currency cell, in document order. We want index 1.
TT_BUYING_COL = 1  # 0=TT Selling, 1=TT Buying, 2=OD Buying, 3=Notes Selling, 4=Notes Buying

_LEADING_INT_RE = re.compile(r"^\s*(\d+)\s+")


class MaybankScraper(Scraper):
    """Maybank Malaysia foreign-exchange counter rates page.

    The page is server-rendered: rates are in a <table> in the HTML, no XHR.
    For CNY → MYR we use the **TT Buying** column (bank buys CNY from the
    customer, gives MYR). Rates are quoted per N units of foreign currency
    where N is the leading integer in the row label (e.g., '100 Chinese
    Renminbi'). Stored convention is MYR per 1 CNY, so divide by N.

    The fee_estimate is None — the bank's spread is already baked into the
    buying rate. The RM TT charge applies to outbound transfers, not to
    this counter-rate comparison, so we don't model a separate fee in V1.

    Akamai handling: detect a challenge / blocked page by the absence of
    the rate-table marker; raise ScraperError with a clear message. No
    Playwright fallback in this scraper (separate task if/when needed).
    """

    channel_code: ClassVar[str] = "maybank"
    timeout_seconds: ClassVar[int] = 20
    URL: ClassVar[str] = (
        "https://www.maybank2u.com.my/maybank2u/malaysia/en/personal/rates/forex_rates.page"
    )
    CURRENCY_LABEL_FOR: ClassVar[dict[str, str]] = {
        "CNY": "Chinese Renminbi",
    }

    async def fetch(self, base: str, quote: str) -> ScrapeResult:
        if quote != "MYR":
            raise ScraperError(f"maybank: only MYR quote is supported (got {quote})")
        label_needle = self.CURRENCY_LABEL_FOR.get(base)
        if label_needle is None:
            raise ScraperError(f"maybank: no known label for base {base}")

        html = await self._fetch_page()
        # Akamai interstitials don't have the rate-table marker. If we got
        # one of those instead of the real page, fail clearly rather than
        # silently parse junk.
        if PAGE_MARKER not in html:
            raise ScraperError(
                "maybank: response is missing the rate-table marker "
                f"({PAGE_MARKER!r}); likely an Akamai/WAF challenge page "
                "or empty body. No proxy/cookie workaround in this task."
            )

        row = self._find_currency_row(html, label_needle)
        if row is None:
            raise ScraperError(f"maybank: no row matching {label_needle!r}")

        currency_label, multiplier, columns = row
        if TT_BUYING_COL >= len(columns):
            raise ScraperError(
                f"maybank: only {len(columns)} rate columns in {currency_label!r} row, "
                f"expected ≥ {TT_BUYING_COL + 1}"
            )
        tt_buying_raw = columns[TT_BUYING_COL]
        if tt_buying_raw is None:
            raise ScraperError(
                f"maybank: TT Buying column is N/A for {currency_label!r}; " "cannot compute rate"
            )

        try:
            tt_buying = Decimal(str(tt_buying_raw))
        except Exception as exc:
            raise ScraperError(f"maybank: cannot parse TT Buying {tt_buying_raw!r}: {exc}") from exc
        if multiplier <= 0:
            raise ScraperError(f"maybank: non-positive multiplier {multiplier}")

        rate = (tt_buying / Decimal(multiplier)).quantize(Decimal("0.00000001"))
        if base == "CNY" and quote == "MYR":
            self._sanity_check(rate)

        return ScrapeResult(
            base_currency=base,
            quote_currency=quote,
            rate=rate,
            rate_type="tt_buy",
            raw_payload={
                "currency_label": currency_label,
                "multiplier": multiplier,
                "tt_selling": columns[0] if len(columns) > 0 else None,
                "tt_buying": tt_buying_raw,
                "od_buying": columns[2] if len(columns) > 2 else None,
                "last_update": self._extract_last_update(html),
            },
            # bank spread is already baked into tt_buying; the RM TT charge
            # is for outbound transfers, not for this counter-rate view.
            fee_estimate=None,
            fee_currency=None,
        )

    async def _fetch_page(self) -> str:
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout_seconds,
                headers=BROWSER_HEADERS,
                follow_redirects=True,
            ) as client:
                resp = await client.get(self.URL)
                if resp.status_code == 403:
                    raise ScraperError(
                        "maybank: HTTP 403 from server-side GET — most likely Akamai "
                        "blocked the request. No proxy/cookie workaround in this task."
                    )
                resp.raise_for_status()
                return resp.text
        except httpx.HTTPError as exc:
            raise ScraperError(f"maybank: HTTP error: {exc}") from exc

    def _find_currency_row(
        self, html: str, label_needle: str
    ) -> tuple[str, int, list[str | None]] | None:
        """Locate the <tr> for the target currency. Returns
        (full_label, multiplier, [tt_selling, tt_buying, od_buying,
        notes_selling, notes_buying]) where each cell is the raw text or
        None for N/A. Returns None if the row isn't present."""
        soup = BeautifulSoup(html, "lxml")
        for tr in soup.find_all("tr"):
            if not isinstance(tr, Tag):
                continue
            cur_td = tr.find("td", class_="currency")
            if cur_td is None:
                continue
            span = cur_td.find("span")
            label = (span.get_text(strip=True) if span else cur_td.get_text(strip=True)) or ""
            if label_needle.lower() not in label.lower():
                continue

            # multiplier = leading integer in the label, default 1.
            m = _LEADING_INT_RE.match(label)
            multiplier = int(m.group(1)) if m else 1

            # Rate cells: the <td>s following the currency cell, in order.
            rate_cells: list[str | None] = []
            for sib in cur_td.find_next_siblings("td"):
                txt = sib.get_text(" ", strip=True)
                if not txt:
                    # Skip leading/trailing empty wrapper tds.
                    continue
                if txt.upper() == "N/A":
                    rate_cells.append(None)
                else:
                    rate_cells.append(txt)
            return label, multiplier, rate_cells
        return None

    @staticmethod
    def _extract_last_update(html: str) -> str | None:
        """Best-effort scrape of the 'Last Update' timestamp. The page shows
        it as plain text near the table; if we can't find it, return None."""
        match = re.search(
            r"Last\s+Update[^A-Za-z0-9]*([A-Za-z]+\s+\d{1,2},\s*\d{4}\s+\d{1,2}:\d{2}\s*[AP]M)",
            html,
            re.IGNORECASE,
        )
        return match.group(1) if match else None
