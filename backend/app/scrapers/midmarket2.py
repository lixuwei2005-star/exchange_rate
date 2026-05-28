from __future__ import annotations

from decimal import Decimal
from typing import ClassVar

import httpx

from app.scrapers.base import Scraper, ScraperError, ScrapeResult

UA = "rate.005917.xyz contact: lixuwei2005@gmail.com"


class Midmarket2Scraper(Scraper):
    """Secondary midmarket reference via api.exchangerate.fun.

    Source: https://github.com/haxqer/FreeExchangeRateApi — a public free
    aggregator that returns USD-based midmarket rates derived from multiple
    upstreams. Accepting `?base=CNY` returns a JSON shape identical to
    Frankfurter's:

        {"timestamp": <unix>, "base": "CNY", "rates": {"MYR": 0.586818, ...}}

    For our `CNY -> MYR` direction we read `rates.MYR` straight; same as
    the primary midmarket. Treated as a second reference / cross-check
    against Frankfurter — small disagreements between the two are
    expected (different upstreams, slightly different snapshot times).
    """

    channel_code: ClassVar[str] = "midmarket2"
    timeout_seconds: ClassVar[int] = 15
    BASE_URL: ClassVar[str] = "https://api.exchangerate.fun/latest"

    async def fetch(self, base: str, quote: str) -> ScrapeResult:
        params = {"base": base}
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
            raise ScraperError(f"midmarket2: HTTP error: {exc}") from exc

        return self._parse(payload, base=base, quote=quote)

    # ---- pure parser --------------------------------------------------

    def _parse(self, payload: object, *, base: str, quote: str) -> ScrapeResult:
        if not isinstance(payload, dict):
            raise ScraperError(f"midmarket2: response is not a JSON object: {payload!r}")

        # Light defense: the API echoes the base we asked for. If it ever
        # drifts (e.g. silently falls back to USD), bail rather than store
        # a wrongly-normalized rate.
        echoed_base = payload.get("base")
        if echoed_base is not None and echoed_base != base:
            raise ScraperError(f"midmarket2: response.base={echoed_base!r} but asked for {base!r}")

        rates = payload.get("rates")
        if not isinstance(rates, dict):
            raise ScraperError(f"midmarket2: response missing rates dict: {payload!r}")

        raw = rates.get(quote)
        if raw is None:
            raise ScraperError(f"midmarket2: response missing rates.{quote}: {payload!r}")

        try:
            rate = Decimal(str(raw))
        except Exception as exc:
            raise ScraperError(f"midmarket2: cannot parse rate {raw!r}: {exc}") from exc

        if rate <= 0:
            raise ScraperError(f"midmarket2: non-positive rate {rate}")

        rate = rate.quantize(Decimal("0.00000001"))
        if base == "CNY" and quote == "MYR":
            self._sanity_check(rate)

        return ScrapeResult(
            base_currency=base,
            quote_currency=quote,
            rate=rate,
            rate_type="midmarket",
            raw_payload=payload,
            fee_estimate=None,
            fee_currency=None,
        )
