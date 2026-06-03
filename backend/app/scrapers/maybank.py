"""Maybank Malaysia foreign-exchange counter rates — via Firecrawl.

WHY FIRECRAWL (and why this is the one sanctioned exception):
    Maybank's forex page sits behind Akamai Bot Manager, which blocks OCI's
    data-center IP at the IP layer. We confirmed in 2026-05 that even a real
    Playwright browser launched from OCI got an interstitial, so no
    client-side trick (headers, curl_cffi JA3, full browser) can help — the
    block is on the IP, not the fingerprint. Firecrawl fetches the page from
    its own infrastructure and hands back the HTML.

    CLAUDE.md §7/§13 say "never use proxies / unblock services to bypass IP
    blocks". This scraper is the SINGLE, explicit carve-out to that rule,
    approved for Maybank only (the project owner amended the policy 2026-05-30).
    No other channel may use Firecrawl. We still:
      - present our real project User-Agent inside the request,
      - parse the rate with deterministic code (NOT an LLM — §2 correctness),
      - keep the once-a-day cadence so we hit the source ~30×/month.

NORMALIZATION (see CLAUDE.md §2.5):
    The page quotes MYR per N units of foreign currency, with N baked into the
    row label (e.g. "100 Chinese Renminbi"). For CNY → MYR the customer hands
    CNY to the bank and receives MYR → the bank BUYS CNY → use the **Buying TT**
    column. Stored convention is MYR per 1 CNY, so divide by N.

    fee_estimate is None: the spread is already inside Buying TT, and the flat
    RM TT charge applies to outbound transfers, not to this counter-rate view.
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any, ClassVar

import httpx
from bs4 import BeautifulSoup, Tag

from app.config import get_settings
from app.scrapers.base import Scraper, ScraperError, ScrapeResult

# Firecrawl synchronous scrape endpoint (v1). Returns the rendered page in the
# same response — no polling needed.
FIRECRAWL_ENDPOINT = "https://api.firecrawl.dev/v1/scrape"

# Akamai Bot Manager is aggressive, so we ask Firecrawl for its stealth proxy
# pool. It costs more Firecrawl credits per call (~5 vs 1) but at one call/day
# (~30/month, ~150 credits) we stay well inside the free tier. If Firecrawl
# ever rejects this value, fall back to "auto" or "basic".
# TODO recheck-2026-11: confirm Firecrawl still accepts proxy="stealth".
FIRECRAWL_PROXY = "stealth"

# Page-presence marker. If the returned HTML lacks this, we got a challenge /
# error page (even Firecrawl can be blocked), so we bail loud instead of
# parsing junk.
PAGE_MARKER = "Chinese Renminbi"

# Within the row's numeric cells, in document order:
#   0 = Selling TT/OD, 1 = Buying TT, 2 = Buying OD, [3.. = Notes columns]
# We want Buying TT. NOTE: this column index was never verified against live
# Maybank HTML (the source was blocked from OCI for the whole pre-Firecrawl
# era). The full ordered list is stored in raw_payload["rate_columns"] so the
# first live run can be eyeballed against the website. The [0.5, 0.8] sanity
# check is the backstop for a gross mis-pick (wrong currency / forgot ÷N);
# TT-sell vs TT-buy are close enough that only manual verification catches a
# 1-column slip.
BUYING_TT_COL = 1

_LEADING_INT_RE = re.compile(r"^\s*(\d+)\b")
# A cell that looks like a rate number (optionally with thousands commas).
_NUMERIC_RE = re.compile(r"^\d[\d,]*\.\d+$|^\d[\d,]*$")


class MaybankScraper(Scraper):
    """Maybank counter forex rates, fetched through Firecrawl (see module docstring)."""

    channel_code: ClassVar[str] = "maybank"
    # Firecrawl render + stealth proxy can take 20-40s; give it room.
    timeout_seconds: ClassVar[int] = 90
    URL: ClassVar[str] = (
        "https://www.maybank2u.com.my/maybank2u/malaysia/en/personal/rates/forex_rates.page"
    )
    CURRENCY_LABEL_FOR: ClassVar[dict[str, str]] = {
        "CNY": "Chinese Renminbi",
    }

    async def fetch(self, base: str, quote: str) -> ScrapeResult:
        if base != "CNY":
            raise ScraperError(f"maybank: only CNY base is supported (got {base})")
        if quote != "MYR":
            raise ScraperError(f"maybank: only MYR quote is supported (got {quote})")
        label_needle = self.CURRENCY_LABEL_FOR.get(base)
        if label_needle is None:
            raise ScraperError(f"maybank: no known label for base {base}")

        html, source_status = await self._fetch_via_firecrawl()
        return self._parse(
            html,
            base=base,
            quote=quote,
            label_needle=label_needle,
            source_status=source_status,
        )

    # ---- network ------------------------------------------------------

    async def _fetch_via_firecrawl(self) -> tuple[str, int | None]:
        """POST to Firecrawl and return (page_html, upstream_status_code).

        Empty FIRECRAWL_API_KEY short-circuits to a clear error WITHOUT a
        network call — keeps admin logs clean and avoids burning quota.
        """
        key = get_settings().firecrawl_api_key
        if not key:
            raise ScraperError(
                "maybank: FIRECRAWL_API_KEY is not set. Add it to .env and "
                "restart the backend container. (Maybank requires Firecrawl — "
                "Akamai blocks direct fetches from OCI; see CLAUDE.md §6/§7.)"
            )

        body: dict[str, Any] = {
            "url": self.URL,
            "formats": ["rawHtml"],
            "onlyMainContent": False,
            "waitFor": 3000,  # let the rate table's JS settle
            "timeout": 60000,  # Firecrawl-side cap (ms)
            "proxy": FIRECRAWL_PROXY,
            # Force a LIVE fetch. Firecrawl /v1/scrape defaults to returning a
            # cached result (~2-day maxAge) when it has scraped this URL
            # recently — which made our daily poll keep returning a stale rate
            # for days after Maybank actually updated. maxAge=0 disables the
            # read-through cache so every poll re-fetches the live page.
            # See CLAUDE.md §6. # TODO recheck-2026-11: confirm key name `maxAge`.
            "maxAge": 0,
        }
        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            # We do not hide who we are, even through Firecrawl (§7 ethic).
            "User-Agent": "rate.005917.xyz contact: lixuwei2005@gmail.com",
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                resp = await client.post(FIRECRAWL_ENDPOINT, json=body, headers=headers)
                if resp.status_code == 402:
                    raise ScraperError(
                        "maybank: Firecrawl returned 402 — free credits exhausted "
                        "for this billing period. Channel will recover next cycle."
                    )
                if resp.status_code == 401:
                    raise ScraperError("maybank: Firecrawl returned 401 — bad FIRECRAWL_API_KEY.")
                resp.raise_for_status()
                payload = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ScraperError(f"maybank: Firecrawl request failed: {exc}") from exc

        if not isinstance(payload, dict) or not payload.get("success"):
            err = payload.get("error") if isinstance(payload, dict) else payload
            raise ScraperError(f"maybank: Firecrawl success=false: {err!r}")

        data = payload.get("data") or {}
        html = data.get("rawHtml") or data.get("html")
        if not html:
            raise ScraperError("maybank: Firecrawl response carried no rawHtml/html body")
        meta = data.get("metadata") or {}
        source_status = meta.get("statusCode")
        return html, source_status

    # ---- pure parser --------------------------------------------------

    def _parse(
        self,
        html: str,
        *,
        base: str,
        quote: str,
        label_needle: str,
        source_status: int | None = None,
    ) -> ScrapeResult:
        if PAGE_MARKER not in html:
            raise ScraperError(
                "maybank: response is missing the rate-table marker "
                f"({PAGE_MARKER!r}); Firecrawl likely returned an Akamai "
                "challenge / error page rather than the rate table."
            )

        row = self._find_currency_row(html, label_needle)
        if row is None:
            raise ScraperError(f"maybank: no row containing {label_needle!r}")
        label, multiplier, numeric_cells = row

        if BUYING_TT_COL >= len(numeric_cells):
            raise ScraperError(
                f"maybank: only {len(numeric_cells)} numeric cells in {label!r} row, "
                f"expected ≥ {BUYING_TT_COL + 1} (Buying TT)"
            )
        buying_tt_raw = numeric_cells[BUYING_TT_COL]

        try:
            buying_tt = Decimal(buying_tt_raw.replace(",", ""))
        except Exception as exc:
            raise ScraperError(f"maybank: cannot parse Buying TT {buying_tt_raw!r}: {exc}") from exc
        if buying_tt <= 0:
            raise ScraperError(f"maybank: Buying TT is zero/negative for {label!r} — unavailable")
        if multiplier <= 0:
            raise ScraperError(f"maybank: non-positive multiplier {multiplier}")

        rate = (buying_tt / Decimal(multiplier)).quantize(Decimal("0.00000001"))
        if base == "CNY" and quote == "MYR":
            self._sanity_check(rate)

        return ScrapeResult(
            base_currency=base,
            quote_currency=quote,
            rate=rate,
            rate_type="tt_buy",
            raw_payload={
                "currency_label": label,
                "multiplier": multiplier,
                # Full ordered list so the first live run can be verified by
                # eye against the Maybank website (which column is Buying TT).
                "rate_columns": numeric_cells,
                "selling_tt_od": numeric_cells[0] if len(numeric_cells) > 0 else None,
                "buying_tt": buying_tt_raw,
                "buying_od": numeric_cells[2] if len(numeric_cells) > 2 else None,
                "via": "firecrawl",
                "firecrawl_proxy": FIRECRAWL_PROXY,
                "source_status_code": source_status,
                "last_update": self._extract_last_update(html),
            },
            fee_estimate=None,
            fee_currency=None,
        )

    def _find_currency_row(self, html: str, label_needle: str) -> tuple[str, int, list[str]] | None:
        """Find the <tr> for the target currency.

        Returns (label_text, multiplier, [numeric cell texts in order]) or
        None. The multiplier is the leading integer in the label cell
        ("100 Chinese Renminbi" → 100, default 1). Numeric cells are every
        cell AFTER the label cell whose text parses as a number.
        """
        soup = BeautifulSoup(html, "lxml")
        needle = label_needle.lower()
        for tr in soup.find_all("tr"):
            if not isinstance(tr, Tag):
                continue
            cells = [c for c in tr.find_all(["td", "th"]) if isinstance(c, Tag)]
            if not cells:
                continue
            # Locate the cell that names the currency.
            label_idx: int | None = None
            label_text = ""
            for i, c in enumerate(cells):
                txt = c.get_text(" ", strip=True)
                if needle in txt.lower():
                    label_idx = i
                    label_text = txt
                    break
            if label_idx is None:
                continue

            m = _LEADING_INT_RE.match(label_text)
            multiplier = int(m.group(1)) if m else 1

            numeric_cells: list[str] = []
            for c in cells[label_idx + 1 :]:
                txt = c.get_text(" ", strip=True)
                if txt and _NUMERIC_RE.match(txt):
                    numeric_cells.append(txt)
            if not numeric_cells:
                # Found the label but no numbers beside it — keep scanning in
                # case another row holds the actual data.
                continue
            return label_text, multiplier, numeric_cells
        return None

    @staticmethod
    def _extract_last_update(html: str) -> str | None:
        """Best-effort scrape of the 'Last Update' timestamp; None if absent."""
        match = re.search(
            r"Last\s+Update[^A-Za-z0-9]*" r"([A-Za-z]+\s+\d{1,2},\s*\d{4}\s+\d{1,2}:\d{2}\s*[AP]M)",
            html,
            re.IGNORECASE,
        )
        return match.group(1) if match else None
