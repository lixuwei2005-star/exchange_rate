from __future__ import annotations

from typing import ClassVar

import httpx

from app.scrapers._common import make_client, to_decimal
from app.scrapers.base import Scraper, ScraperError, ScrapeResult


class WiseScraper(Scraper):
    """Wise public rate endpoint. Returns rate as quote per 1 source — exactly
    the direction we store, so no transformation is needed.

    Response shape (as of 2026): an array of { source, target, rate, time }.
    Wise may also gate this behind auth in some regions; on 4xx we surface
    a ScraperError and admins can switch the channel off.
    """

    channel_code: ClassVar[str] = "wise"
    timeout_seconds: ClassVar[int] = 15
    BASE_URL: ClassVar[str] = "https://api.wise.com/v1/rates"

    async def fetch(self, base: str, quote: str) -> ScrapeResult:
        try:
            async with make_client(self.timeout_seconds) as client:
                resp = await client.get(self.BASE_URL, params={"source": base, "target": quote})
                resp.raise_for_status()
                payload = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ScraperError(f"wise: HTTP error: {exc}") from exc

        rate_value: object | None = None
        if isinstance(payload, list) and payload:
            first = payload[0]
            if isinstance(first, dict):
                rate_value = first.get("rate")
        elif isinstance(payload, dict):
            rate_value = payload.get("rate")
        if rate_value is None:
            raise ScraperError(f"wise: response missing rate: {payload!r}")

        try:
            rate = to_decimal(rate_value)
        except Exception as exc:
            raise ScraperError(f"wise: cannot parse rate: {exc}") from exc

        if base == "CNY" and quote == "MYR":
            self._sanity_check(rate)

        return ScrapeResult(
            base_currency=base,
            quote_currency=quote,
            rate=rate,
            rate_type="p2p",
            raw_payload=payload if isinstance(payload, dict) else {"items": payload},
        )
