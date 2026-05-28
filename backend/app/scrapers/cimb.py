from __future__ import annotations

import re
from decimal import Decimal
from typing import ClassVar

import httpx
from bs4 import BeautifulSoup, Tag

from app.scrapers.base import Scraper, ScraperError, ScrapeResult

# Same browser-shape headers we use elsewhere. CIMB's business forex page
# returns a clean HTML doc to a plain server-side GET (unlike Maybank).
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

# Section headings (rendered as plain text right above each <table>). The
# CNY row lives in the 100-units table — see CLAUDE.md §2.5 for why.
SECTION_PER_UNIT = "Per Unit of Foreign Currency"
SECTION_PER_100 = "Per 100 Units of Foreign Currency"
SECTION_NOTES = "Currency Notes"

# Column order in the TT tables, after the leading Country / Country Code:
#   [Selling TT/OD, Buying TT, Buying OD]
BUYING_TT_COL = 1  # 0=Selling TT/OD, 1=Buying TT, 2=Buying OD

# Used as a page-presence marker: if the page doesn't contain the per-100
# section heading, the response is junk and we bail loud.
PAGE_MARKER = SECTION_PER_100

# Per-base-currency: (currency code, which section's table holds it,
# multiplier the section implies).
CURRENCY_CONFIG: dict[str, tuple[str, str, int]] = {
    # CNY is in the per-100-units table.
    "CNY": ("CNY", SECTION_PER_100, 100),
}


class CIMBScraper(Scraper):
    """CIMB Malaysia business forex rates page.

    URL: /en/business/help-and-support/rates-charges/forex-rates.html

    The page server-renders three <table>s, each preceded by a section
    heading that tells you the multiplier:
        - 'Per Unit of Foreign Currency Table'         (USD, EUR, AUD, ...) → ×1
        - 'Per 100 Units of Foreign Currency Table'    (CNY, AED, BDT, ...) → ×100
        - 'Currency Notes Table'                       (physical cash, not used)

    Each TT table's columns are:
        Country | Country Code | Selling TT/OD | Buying TT | Buying OD

    For CNY → MYR (customer hands CNY to the bank, gets MYR → bank BUYS CNY)
    use the **Buying TT** column. Stored rate is MYR per 1 CNY, so divide
    by the section's multiplier (100 for CNY).

    Fee model: fee_estimate is None. The bank's spread is already baked into
    Buying TT; the separate RM TT charge applies to outbound transfers, not
    to this counter-rate comparison.
    """

    channel_code: ClassVar[str] = "cimb"
    timeout_seconds: ClassVar[int] = 20
    URL: ClassVar[str] = (
        "https://www.cimb.com.my/en/business/help-and-support/rates-charges/forex-rates.html"
    )

    async def fetch(self, base: str, quote: str) -> ScrapeResult:
        if quote != "MYR":
            raise ScraperError(f"cimb: only MYR quote is supported (got {quote})")
        cfg = CURRENCY_CONFIG.get(base)
        if cfg is None:
            raise ScraperError(f"cimb: no config for base {base}")
        country_code, section_heading, multiplier = cfg

        html = await self._fetch_html()
        return self._parse(
            html,
            base=base,
            quote=quote,
            country_code=country_code,
            section_heading=section_heading,
            multiplier=multiplier,
        )

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
                        "cimb: HTTP 403 from server-side GET — likely a WAF block. "
                        "Plain GET worked when this scraper was authored; if this "
                        "starts firing we may need to follow Maybank into Playwright."
                    )
                resp.raise_for_status()
                return resp.text
        except httpx.HTTPError as exc:
            raise ScraperError(f"cimb: HTTP error: {exc}") from exc

    # ---- pure parser --------------------------------------------------

    def _parse(
        self,
        html: str,
        *,
        base: str,
        quote: str,
        country_code: str,
        section_heading: str,
        multiplier: int,
    ) -> ScrapeResult:
        if PAGE_MARKER not in html:
            raise ScraperError(
                f"cimb: response is missing the section marker {PAGE_MARKER!r}; "
                "either the page structure changed or we got a WAF page."
            )

        table = self._find_table_after_heading(html, heading=section_heading)
        if table is None:
            raise ScraperError(f"cimb: couldn't locate <table> for section {section_heading!r}")

        row = self._find_row_for_country_code(table, country_code)
        if row is None:
            raise ScraperError(
                f"cimb: no row for country code {country_code!r} in " f"{section_heading!r} table"
            )

        country_label, columns = row
        if BUYING_TT_COL >= len(columns):
            raise ScraperError(
                f"cimb: only {len(columns)} rate columns in {country_code!r} row, "
                f"expected ≥ {BUYING_TT_COL + 1}"
            )
        buying_tt_raw = columns[BUYING_TT_COL]
        if buying_tt_raw is None:
            raise ScraperError(
                f"cimb: Buying TT column is N/A for {country_code!r}; cannot compute rate"
            )

        try:
            buying_tt = Decimal(str(buying_tt_raw))
        except Exception as exc:
            raise ScraperError(f"cimb: cannot parse Buying TT {buying_tt_raw!r}: {exc}") from exc
        if multiplier <= 0:
            raise ScraperError(f"cimb: non-positive multiplier {multiplier}")

        rate = (buying_tt / Decimal(multiplier)).quantize(Decimal("0.00000001"))
        if base == "CNY" and quote == "MYR":
            self._sanity_check(rate)

        return ScrapeResult(
            base_currency=base,
            quote_currency=quote,
            rate=rate,
            rate_type="tt_buy",
            raw_payload={
                "section": section_heading,
                "country_label": country_label,
                "country_code": country_code,
                "multiplier": multiplier,
                "selling_tt_od": columns[0] if len(columns) > 0 else None,
                "buying_tt": buying_tt_raw,
                "buying_od": columns[2] if len(columns) > 2 else None,
                "last_updated": self._extract_last_updated(html, section_heading),
            },
            fee_estimate=None,
            fee_currency=None,
        )

    def _find_table_after_heading(self, html: str, *, heading: str) -> Tag | None:
        """Locate the <table> belonging to a specific section.

        CIMB renders each section as a self-contained
        `<div class="cmp-rates-charges rc-table ...">` wrapper that holds
        BOTH the heading text and exactly one <table>. We find the wrapper
        whose text starts with `heading`, then return its inner table.
        """
        soup = BeautifulSoup(html, "lxml")
        for wrapper in soup.find_all("div", class_=re.compile(r"\brc-table\b")):
            if not isinstance(wrapper, Tag):
                continue
            text = wrapper.get_text(" ", strip=True)
            if not text.startswith(heading):
                continue
            inner_table = wrapper.find("table")
            if isinstance(inner_table, Tag):
                return inner_table
        return None

    def _find_row_for_country_code(
        self, table: Tag, country_code: str
    ) -> tuple[str, list[str | None]] | None:
        """In a TT table, find the <tr> whose second <td> matches the given
        country code. Returns (country_label, [selling_tt, buying_tt,
        buying_od]) with None for N/A cells. None if no row matches."""
        cc_upper = country_code.upper()
        for tr in table.find_all("tr"):
            if not isinstance(tr, Tag):
                continue
            cells = tr.find_all("td")
            if len(cells) < 5:
                # header row or short row — skip
                continue
            code = cells[1].get_text(" ", strip=True).upper()
            if code != cc_upper:
                continue
            country_label = cells[0].get_text(" ", strip=True)
            rate_cells: list[str | None] = []
            for c in cells[2:]:
                txt = c.get_text(" ", strip=True)
                if not txt or txt.upper() == "N/A":
                    rate_cells.append(None)
                else:
                    rate_cells.append(txt)
            return country_label, rate_cells
        return None

    @staticmethod
    def _extract_last_updated(html: str, section_heading: str) -> str | None:
        """Best-effort scrape of the per-table 'Last Updated: ... AM/PM, DD Mon YYYY,
        Weekday' timestamp. Looks for the first such pattern after the section
        heading in the document. Returns None if not found."""
        idx = html.find(section_heading)
        if idx < 0:
            return None
        # Scan a reasonable window after the heading (until the next section
        # or 4 KB, whichever is shorter).
        window = html[idx : idx + 4096]
        match = re.search(
            r"Last\s+Updated[^A-Za-z0-9]*"
            r"(\d{1,2}:\d{2}\s*[apAP][mM],\s*\d{1,2}\s+[A-Za-z]+\s+\d{4}[^<]*)",
            window,
        )
        if not match:
            return None
        return re.sub(r"\s+", " ", match.group(1)).strip(" ,")
