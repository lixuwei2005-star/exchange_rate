from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import ClassVar

import httpx

from app.scrapers._common import make_client, to_decimal
from app.scrapers.base import Scraper, ScraperError, ScrapeResult

# CLAUDE.md §6 — verified 2026-05-27 # TODO recheck-2026-11
MASTERCARD_ISSUER_MARKUP: Decimal = Decimal("0.02")


class MastercardScraper(Scraper):
    """Mastercard currency-converter widget JSON endpoint.

    Returns the network conversion rate; we apply the issuer markup on top.
    Mastercard's calculator backend differs slightly across regions; the URL
    here is the most commonly observed public endpoint.
    """

    channel_code: ClassVar[str] = "mastercard"
    timeout_seconds: ClassVar[int] = 20
    BASE_URL: ClassVar[str] = "https://www.mastercard.us/settlement/currencyrate/conversion-rate"

    async def fetch(self, base: str, quote: str) -> ScrapeResult:
        params = {
            "fxDate": date.today().strftime("%Y-%m-%d"),
            "transCurr": quote,
            "crdhldBillCurr": base,
            "bankFee": "0",
            "transAmt": "1",
        }
        try:
            async with make_client(self.timeout_seconds) as client:
                resp = await client.get(self.BASE_URL, params=params)
                resp.raise_for_status()
                payload = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ScraperError(f"mastercard: HTTP error: {exc}") from exc

        raw_rate = self._extract_rate(payload)
        if raw_rate is None:
            raise ScraperError(f"mastercard: rate field missing: {payload!r}")
        try:
            r = to_decimal(raw_rate)
        except Exception as exc:
            raise ScraperError(f"mastercard: cannot parse rate {raw_rate!r}: {exc}") from exc

        rate = (r * (Decimal("1") - MASTERCARD_ISSUER_MARKUP)).quantize(Decimal("0.00000001"))
        if base == "CNY" and quote == "MYR":
            self._sanity_check(rate)
        return ScrapeResult(
            base_currency=base,
            quote_currency=quote,
            rate=rate,
            rate_type="card_network",
            raw_payload={
                "network_rate": str(r),
                "markup": str(MASTERCARD_ISSUER_MARKUP),
                "raw": payload,
            },
        )

    def _extract_rate(self, payload: object) -> object | None:
        if not isinstance(payload, dict):
            return None
        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        for k in ("conversionRate", "rate", "fxRate"):
            if k in data:
                return data[k]
        return None
