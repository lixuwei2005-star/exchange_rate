from __future__ import annotations

from decimal import Decimal
from typing import ClassVar

import httpx

from app.scrapers.base import Scraper, ScraperError, ScrapeResult

UA = "rate.005917.xyz contact: lixuwei2005@gmail.com"


class MidmarketScraper(Scraper):
    """Frankfurter (ECB-derived) midmarket reference rate.

    Frankfurter returns `1 from = X to`, so for base=CNY/quote=MYR the value
    in `rates.MYR` is already MYR per 1 CNY — no transformation needed.
    """

    channel_code: ClassVar[str] = "midmarket"
    timeout_seconds: ClassVar[int] = 15
    # frankfurter.app 301s to frankfurter.dev/v1/* since early 2026. We point
    # at the new canonical URL AND follow redirects for resilience.
    BASE_URL: ClassVar[str] = "https://api.frankfurter.dev/v1/latest"

    async def fetch(self, base: str, quote: str) -> ScrapeResult:
        params = {"from": base, "to": quote}
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout_seconds,
                headers={"User-Agent": UA},
                follow_redirects=True,
            ) as client:
                resp = await client.get(self.BASE_URL, params=params)
                resp.raise_for_status()
                payload = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ScraperError(f"midmarket: HTTP error: {exc}") from exc

        rates = payload.get("rates") or {}
        raw = rates.get(quote)
        if raw is None:
            raise ScraperError(f"midmarket: response missing rates.{quote}: {payload}")
        try:
            rate = Decimal(str(raw))
        except Exception as exc:
            raise ScraperError(f"midmarket: cannot parse rate {raw!r}: {exc}") from exc

        # Sanity check (CLAUDE.md §2.6) — only for CNY->MYR. For other pairs in
        # V2 this guard would need a per-pair window; for V1 always-CNY/MYR it's fine.
        if base == "CNY" and quote == "MYR":
            self._sanity_check(rate)

        return ScrapeResult(
            base_currency=base,
            quote_currency=quote,
            rate=rate,
            rate_type="midmarket",
            raw_payload=payload,
        )
