from __future__ import annotations

from decimal import Decimal
from typing import Any, ClassVar

import httpx

from app.config import get_settings
from app.scrapers.base import Scraper, ScraperError, ScrapeResult

UA = "rate.005917.xyz contact: lixuwei2005@gmail.com"


class Midmarket3Scraper(Scraper):
    """Third midmarket reference via exchangerate-api.com v6.

    Source: https://www.exchangerate-api.com/docs — authenticated JSON
    endpoint at `/v6/{key}/latest/{base}`. Updated daily (the response
    advertises `time_last_update_unix` + `time_next_update_unix` so we
    know exactly when the next refresh happens upstream — polling more
    often than that is harmless but pointless).

    Response shape:

        {
          "result": "success",
          "base_code": "CNY",
          "time_last_update_unix": 1779926401,
          "time_last_update_utc": "Thu, 28 May 2026 00:00:01 +0000",
          "time_next_update_unix": 1780012801,
          "conversion_rates": {"MYR": 0.5831, "USD": 0.1472, ...}
        }

    Quirk vs other midmarkets: the rates dict is named `conversion_rates`
    (not `rates`); the success indicator is `result == "success"` (with
    `"error"` + `error-type` on failure).

    The API key is read from EXCHANGERATE_API_KEY env (.env), never
    committed. Empty key short-circuits to ScraperError WITHOUT making
    a request — keeps the error message clean in admin logs and avoids
    burning the free-tier quota with bad calls.
    """

    channel_code: ClassVar[str] = "midmarket3"
    timeout_seconds: ClassVar[int] = 15
    URL_TEMPLATE: ClassVar[str] = "https://v6.exchangerate-api.com/v6/{key}/latest/{base}"

    async def fetch(self, base: str, quote: str) -> ScrapeResult:
        key = get_settings().exchangerate_api_key
        if not key:
            raise ScraperError(
                "midmarket3: EXCHANGERATE_API_KEY is not set. "
                "Add it to .env and restart the backend container."
            )
        url = self.URL_TEMPLATE.format(key=key, base=base)
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout_seconds,
                headers={"User-Agent": UA},
                follow_redirects=True,
            ) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                payload = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ScraperError(f"midmarket3: HTTP error: {exc}") from exc

        return self._parse(payload, base=base, quote=quote)

    # ---- pure parser --------------------------------------------------

    def _parse(self, payload: Any, *, base: str, quote: str) -> ScrapeResult:
        if not isinstance(payload, dict):
            raise ScraperError(f"midmarket3: response is not a JSON object: {payload!r}")

        result = payload.get("result")
        if result != "success":
            err = payload.get("error-type") or payload.get("error_type") or "unknown"
            raise ScraperError(f"midmarket3: API returned result={result!r}, error-type={err!r}")

        echoed_base = payload.get("base_code")
        if echoed_base is not None and echoed_base != base:
            raise ScraperError(f"midmarket3: base_code={echoed_base!r} but asked for {base!r}")

        rates = payload.get("conversion_rates")
        if not isinstance(rates, dict):
            raise ScraperError(f"midmarket3: response missing conversion_rates dict: {payload!r}")

        raw = rates.get(quote)
        if raw is None:
            raise ScraperError(f"midmarket3: conversion_rates.{quote} missing: {payload!r}")

        try:
            rate = Decimal(str(raw))
        except Exception as exc:
            raise ScraperError(f"midmarket3: cannot parse rate {raw!r}: {exc}") from exc

        if rate <= 0:
            raise ScraperError(f"midmarket3: non-positive rate {rate}")

        rate = rate.quantize(Decimal("0.00000001"))
        if base == "CNY" and quote == "MYR":
            self._sanity_check(rate)

        return ScrapeResult(
            base_currency=base,
            quote_currency=quote,
            rate=rate,
            rate_type="midmarket",
            raw_payload={
                "result": result,
                "base_code": echoed_base,
                "rate_for_quote": str(raw),
                "time_last_update_unix": payload.get("time_last_update_unix"),
                "time_last_update_utc": payload.get("time_last_update_utc"),
                "time_next_update_unix": payload.get("time_next_update_unix"),
            },
            fee_estimate=None,
            fee_currency=None,
        )
