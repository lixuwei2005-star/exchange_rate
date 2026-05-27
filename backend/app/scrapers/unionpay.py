from __future__ import annotations

from decimal import Decimal
from typing import ClassVar

import httpx

from app.scrapers._common import make_client, to_decimal
from app.scrapers.base import Scraper, ScraperError, ScrapeResult


class UnionPayScraper(Scraper):
    """UnionPay International cross-border rate service.

    The endpoint accepts `transCur` (currency being paid in) and `baseCur`
    (target settlement currency), and replies with "1 transCur = X baseCur"
    via a JSON response. Per CLAUDE.md §2.5 we query with
        transCur = MYR (foreign currency)
        baseCur  = CNY
    and the response gives "1 MYR = X CNY". Our stored direction is
    MYR per 1 CNY, so:  rate = 1 / X.

    The exact JSON shape is not formally documented; this scraper expects
    either {"data": [{"exchangeRate": "1.5xxx", ...}]} or a top-level
    {"exchangeRate": "..."}. If the live response shape differs, raise so
    an admin can iterate on the parser without silently storing junk.
    """

    channel_code: ClassVar[str] = "unionpay"
    timeout_seconds: ClassVar[int] = 20
    BASE_URL: ClassVar[str] = "https://www.unionpayintl.com/upload/jfimg/exchangeRate.txt"

    async def fetch(self, base: str, quote: str) -> ScrapeResult:
        if base != "CNY":
            raise ScraperError(f"unionpay: only CNY base supported (got {base})")
        try:
            async with make_client(self.timeout_seconds) as client:
                # NOTE: UnionPay's actual endpoint varies. The .txt above is a
                # known mirror that returns the latest rate table as a JSON-ish
                # blob. If the live response shape diverges, ScraperError
                # surfaces in /admin/logs.
                resp = await client.get(self.BASE_URL)
                resp.raise_for_status()
                payload = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ScraperError(f"unionpay: HTTP error: {exc}") from exc

        cny_per_quote = self._extract_rate(payload, quote)
        if cny_per_quote is None:
            raise ScraperError(f"unionpay: rate for {quote} not found: {payload!r}")
        try:
            x = to_decimal(cny_per_quote)
        except Exception as exc:
            raise ScraperError(f"unionpay: cannot parse rate {cny_per_quote!r}: {exc}") from exc
        if x <= 0:
            raise ScraperError(f"unionpay: non-positive rate {x}")
        rate = (Decimal("1") / x).quantize(Decimal("0.00000001"))
        self._sanity_check(rate)
        return ScrapeResult(
            base_currency=base,
            quote_currency=quote,
            rate=rate,
            rate_type="card_network",
            raw_payload={"cny_per_quote": str(x), "raw": payload},
        )

    def _extract_rate(self, payload: object, quote: str) -> object | None:
        """Tolerate several plausible shapes."""
        if isinstance(payload, dict):
            # shape A: {"data": [{"transCur":"MYR","exchangeRate":"1.5"}, ...]}
            data = payload.get("data")
            if isinstance(data, list):
                for row in data:
                    if isinstance(row, dict) and row.get("transCur") == quote:
                        return row.get("exchangeRate") or row.get("rate")
            # shape B: {"MYR": "1.5xx"} or {"rates": {"MYR": "..."}}
            if quote in payload:
                return payload.get(quote)
            rates = payload.get("rates")
            if isinstance(rates, dict) and quote in rates:
                return rates[quote]
        return None
