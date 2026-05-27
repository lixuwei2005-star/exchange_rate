from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import ClassVar

import httpx

from app.scrapers._common import make_client, to_decimal
from app.scrapers.base import Scraper, ScraperError, ScrapeResult

# Issuer markup applied on top of the Visa network rate (CLAUDE.md §6).
# ~2% is conservative; real value varies by card issuer.
# Source: CLAUDE.md §6 — verified 2026-05-27 # TODO recheck-2026-11
VISA_ISSUER_MARKUP: Decimal = Decimal("0.02")


class VisaScraper(Scraper):
    """Visa exchange-rate calculator JSON endpoint.

    The calculator widget posts to an internal API that returns
    `{"originalValues": {..., "fxRate": "0.6582", "fromCurrency": "CNY",
       "toCurrency": "MYR", ...}}`. We apply the issuer markup once on top.

    URL/params here are inferred from the public widget; if the live endpoint
    shape diverges, ScraperError surfaces in /admin/logs.
    """

    channel_code: ClassVar[str] = "visa"
    timeout_seconds: ClassVar[int] = 20
    BASE_URL: ClassVar[str] = "https://www.visa.com.my/cmsapi/fx/rates"

    async def fetch(self, base: str, quote: str) -> ScrapeResult:
        params = {
            "amount": "1",
            "fee": "0",
            "fromCurr": base,
            "toCurr": quote,
            "utcConvertedDate": date.today().strftime("%m/%d/%Y"),
            "exchangedate": date.today().strftime("%m/%d/%Y"),
        }
        try:
            async with make_client(self.timeout_seconds) as client:
                resp = await client.get(self.BASE_URL, params=params)
                resp.raise_for_status()
                payload = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ScraperError(f"visa: HTTP error: {exc}") from exc

        raw_rate = self._extract_rate(payload)
        if raw_rate is None:
            raise ScraperError(f"visa: rate field missing: {payload!r}")
        try:
            r = to_decimal(raw_rate)
        except Exception as exc:
            raise ScraperError(f"visa: cannot parse rate {raw_rate!r}: {exc}") from exc

        rate = (r * (Decimal("1") - VISA_ISSUER_MARKUP)).quantize(Decimal("0.00000001"))
        if base == "CNY" and quote == "MYR":
            self._sanity_check(rate)
        return ScrapeResult(
            base_currency=base,
            quote_currency=quote,
            rate=rate,
            rate_type="card_network",
            raw_payload={"network_rate": str(r), "markup": str(VISA_ISSUER_MARKUP), "raw": payload},
        )

    def _extract_rate(self, payload: object) -> object | None:
        if not isinstance(payload, dict):
            return None
        # common shape: {"originalValues":{"fxRate":"0.6582", ...}}
        original = payload.get("originalValues") or payload.get("convertedAmount")
        if isinstance(original, dict):
            for k in ("fxRate", "fxRateVisa", "rate"):
                if k in original:
                    return original[k]
        for k in ("fxRate", "rate"):
            if k in payload:
                return payload[k]
        return None
