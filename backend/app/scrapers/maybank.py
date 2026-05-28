from __future__ import annotations

import logging
import re
from decimal import Decimal
from typing import ClassVar

import httpx
from bs4 import BeautifulSoup, Tag

from app.scrapers.base import Scraper, ScraperError, ScrapeResult

logger = logging.getLogger(__name__)

# Realistic desktop Chrome 124 on Windows 10 / x64. Matches default Playwright
# Chromium so the navigator fingerprint stays consistent end-to-end.
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
BROWSER_HEADERS: dict[str, str] = {
    "User-Agent": BROWSER_UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

# Page-presence marker. If the HTML doesn't contain this string the response
# is almost certainly an Akamai/WAF challenge — fail loud rather than parse junk.
PAGE_MARKER = "Chinese Renminbi"

# Stealth init script — applied before page navigation. Hides the most common
# headless signals Akamai's client-side detection looks at. Doesn't make the
# browser undetectable; just removes the obvious tells.
STEALTH_INIT_SCRIPT = """
(() => {
  // navigator.webdriver: stock Playwright leaks this as true.
  Object.defineProperty(navigator, 'webdriver', { get: () => undefined });

  // Provide non-empty plugin/mimetype arrays.
  Object.defineProperty(navigator, 'plugins', {
    get: () => [
      { name: 'Chrome PDF Plugin' },
      { name: 'Chrome PDF Viewer' },
      { name: 'Native Client' },
    ],
  });

  Object.defineProperty(navigator, 'languages', {
    get: () => ['en-US', 'en'],
  });

  // window.chrome exists on real Chrome.
  if (!window.chrome) {
    window.chrome = { runtime: {} };
  }

  // navigator.permissions.query reports differently for notifications.
  const originalQuery = window.navigator.permissions?.query;
  if (originalQuery) {
    window.navigator.permissions.query = (parameters) =>
      parameters.name === 'notifications'
        ? Promise.resolve({ state: Notification.permission })
        : originalQuery(parameters);
  }
})();
"""

# Columns AFTER the currency cell, in document order. We want index 1.
TT_BUYING_COL = 1  # 0=TT Selling, 1=TT Buying, 2=OD Buying, 3=Notes Selling, 4=Notes Buying

_LEADING_INT_RE = re.compile(r"^\s*(\d+)\s+")


class MaybankScraper(Scraper):
    """Maybank Malaysia foreign-exchange counter rates page.

    The page is server-rendered (rates live in a <table> in HTML, no XHR) but
    sits behind Akamai Bot Manager. A plain server-side httpx GET returns 403
    from datacenter IPs (e.g. OCI). The scraper fetches via Playwright + a
    short stealth init script first; if Playwright fails to launch (Chromium
    not installed in the image), it falls back to httpx so the scraper at
    least returns a useful error.

    Parse rules (CLAUDE.md §2.5):
      - Locate <td class='currency'> row whose <span> text contains
        'Chinese Renminbi'.
      - Pull the leading integer as the multiplier (e.g., 100 in '100
        Chinese Renminbi'). Don't hardcode 100; other currencies use 1.
      - After the currency cell: [TT Selling, TT Buying, OD Buying,
        Notes Selling, Notes Buying] — take index 1 (TT Buying).
      - rate = Decimal(tt_buying) / Decimal(multiplier). Use Decimal(str(...))
        end-to-end, never float.

    Fee model: fee_estimate is None. The bank's spread is already baked into
    the buying rate; the RM TT charge applies to outbound transfers, not to
    this counter-rate comparison.
    """

    channel_code: ClassVar[str] = "maybank"
    timeout_seconds: ClassVar[int] = 30
    URL: ClassVar[str] = (
        "https://www.maybank2u.com.my/maybank2u/malaysia/en/personal/rates/forex_rates.page"
    )
    PAGE_WAIT_TIMEOUT_MS: ClassVar[int] = 15_000
    NAV_TIMEOUT_MS: ClassVar[int] = 30_000

    CURRENCY_LABEL_FOR: ClassVar[dict[str, str]] = {
        "CNY": "Chinese Renminbi",
    }

    async def fetch(self, base: str, quote: str) -> ScrapeResult:
        if quote != "MYR":
            raise ScraperError(f"maybank: only MYR quote is supported (got {quote})")
        label_needle = self.CURRENCY_LABEL_FOR.get(base)
        if label_needle is None:
            raise ScraperError(f"maybank: no known label for base {base}")

        html = await self._fetch_html()
        return self._parse(html, base=base, quote=quote, label_needle=label_needle)

    # ---- I/O paths ----------------------------------------------------

    async def _fetch_html(self) -> str:
        """Fetch the rates page HTML. Tries Playwright first (gets past
        Akamai); falls back to httpx so the scraper still returns a
        sensible error when Chromium isn't installed in the image."""
        try:
            return await self._fetch_via_playwright()
        except _PlaywrightUnavailable as exc:
            logger.warning("maybank: %s; falling back to httpx", exc)
            return await self._fetch_via_httpx()

    async def _fetch_via_playwright(self) -> str:
        try:
            from playwright.async_api import (
                TimeoutError as PWTimeout,
            )
            from playwright.async_api import (
                async_playwright,
            )
        except ImportError as exc:
            raise _PlaywrightUnavailable(f"playwright package not installed: {exc}") from exc

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=[
                        # Lots of headless detectors look for this exact flag
                        # in the Chromium command line via the Args API. Hide it.
                        "--disable-blink-features=AutomationControlled",
                        "--no-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-gpu",
                    ],
                )
                try:
                    context = await browser.new_context(
                        user_agent=BROWSER_UA,
                        viewport={"width": 1920, "height": 1080},
                        locale="en-US",
                        timezone_id="Asia/Kuala_Lumpur",
                        extra_http_headers={
                            "Accept-Language": BROWSER_HEADERS["Accept-Language"],
                        },
                    )
                    await context.add_init_script(STEALTH_INIT_SCRIPT)
                    page = await context.new_page()
                    try:
                        await page.goto(
                            self.URL,
                            wait_until="domcontentloaded",
                            timeout=self.NAV_TIMEOUT_MS,
                        )
                        # Wait for the marker text to appear in the DOM. If it
                        # doesn't show within the timeout we're almost certainly
                        # on an Akamai interstitial — fail loud.
                        try:
                            await page.wait_for_selector(
                                f"text={PAGE_MARKER}", timeout=self.PAGE_WAIT_TIMEOUT_MS
                            )
                        except PWTimeout as exc:
                            raise ScraperError(
                                f"maybank (playwright): {PAGE_MARKER!r} did not appear "
                                f"within {self.PAGE_WAIT_TIMEOUT_MS / 1000:.0f}s — likely "
                                "an Akamai challenge page. Stealth tweaks aren't enough; "
                                "needs a paid bypass service or a different source."
                            ) from exc
                        return await page.content()
                    finally:
                        await page.close()
                finally:
                    await browser.close()
        except ScraperError:
            raise
        except _PlaywrightUnavailable:
            raise
        except Exception as exc:
            # Playwright is installed but the launch failed (likely the
            # Chromium binary isn't installed in this image). Treat as
            # "unavailable" so we fall back to httpx.
            raise _PlaywrightUnavailable(f"playwright launch failed: {exc}") from exc

    async def _fetch_via_httpx(self) -> str:
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout_seconds,
                headers=BROWSER_HEADERS,
                follow_redirects=True,
            ) as client:
                resp = await client.get(self.URL)
                if resp.status_code == 403:
                    raise ScraperError(
                        "maybank: HTTP 403 from httpx fallback — Akamai blocked. "
                        "Playwright wasn't available; install Chromium in the image "
                        "(`playwright install chromium` in the Dockerfile)."
                    )
                resp.raise_for_status()
                return resp.text
        except httpx.HTTPError as exc:
            raise ScraperError(f"maybank: HTTP error: {exc}") from exc

    # ---- pure parser --------------------------------------------------

    def _parse(self, html: str, *, base: str, quote: str, label_needle: str) -> ScrapeResult:
        if PAGE_MARKER not in html:
            raise ScraperError(
                f"maybank: response is missing the rate-table marker ({PAGE_MARKER!r}); "
                "likely an Akamai/WAF challenge page or empty body."
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
                f"maybank: TT Buying column is N/A for {currency_label!r}; cannot compute rate"
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
            fee_estimate=None,
            fee_currency=None,
        )

    def _find_currency_row(
        self, html: str, label_needle: str
    ) -> tuple[str, int, list[str | None]] | None:
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

            m = _LEADING_INT_RE.match(label)
            multiplier = int(m.group(1)) if m else 1

            rate_cells: list[str | None] = []
            for sib in cur_td.find_next_siblings("td"):
                txt = sib.get_text(" ", strip=True)
                if not txt:
                    continue
                if txt.upper() == "N/A":
                    rate_cells.append(None)
                else:
                    rate_cells.append(txt)
            return label, multiplier, rate_cells
        return None

    @staticmethod
    def _extract_last_update(html: str) -> str | None:
        match = re.search(
            r"Last\s+Update[^A-Za-z0-9]*([A-Za-z]+\s+\d{1,2},\s*\d{4}\s+\d{1,2}:\d{2}\s*[AP]M)",
            html,
            re.IGNORECASE,
        )
        return match.group(1) if match else None


class _PlaywrightUnavailable(RuntimeError):
    """Raised when Playwright can't run in this environment so the scraper
    falls back to httpx. Not a permanent failure of the scrape itself."""
