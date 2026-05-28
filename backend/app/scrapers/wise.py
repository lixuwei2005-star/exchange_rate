from __future__ import annotations

from decimal import Decimal
from typing import ClassVar

import httpx

from app.scrapers._common import make_client, to_decimal
from app.scrapers.base import Scraper, ScraperError, ScrapeResult


class WiseScraper(Scraper):
    """Wise unauthenticated quote endpoint.

    Stores the EFFECTIVE rate (targetAmount/sourceAmount on the preferred
    paymentOption) — i.e. what the customer actually receives per unit of
    source currency, **after** Wise's fee. This makes Wise comparable apples-
    to-apples with the other channels on the homepage's '你能拿到' column
    without any further frontend math. `fee_estimate` is also captured for
    transparency.

    Preferred paymentOption: BANK_TRANSFER → BANK_TRANSFER. If absent, picks
    the option with the lowest fee. If `paymentOptions` is empty or unusable,
    falls back to the response's top-level `rate` (mid-market, no fee info).
    """

    channel_code: ClassVar[str] = "wise"
    timeout_seconds: ClassVar[int] = 15
    BASE_URL: ClassVar[str] = "https://api.wise.com/v3/quotes"
    REFERENCE_SOURCE_AMOUNT: ClassVar[int] = 1000
    PREFERRED_PAY_IN: ClassVar[str] = "BANK_TRANSFER"
    PREFERRED_PAY_OUT: ClassVar[str] = "BANK_TRANSFER"

    async def fetch(self, base: str, quote: str) -> ScrapeResult:
        async with make_client(self.timeout_seconds) as client:
            try:
                payload = await self._request_quote(client, source=base, target=quote)
            except ScraperError as exc:
                return await self._fetch_reverse_pair(client, base, quote, str(exc))

        option = self._select_option(payload)
        if (
            option is not None
            and option.get("sourceAmount") is not None
            and option.get("targetAmount") is not None
        ):
            return self._result_from_option(payload, option, base, quote)

        # No usable option with amounts — fall back to top-level mid-market rate.
        rate_value = payload.get("rate")
        if rate_value is None:
            raise ScraperError(
                f"wise: no paymentOption with amounts and no top-level rate: {payload!r}"
            )
        rate = self._parse_decimal(rate_value, "rate")
        if base == "CNY" and quote == "MYR":
            self._sanity_check(rate)
        return ScrapeResult(
            base_currency=base,
            quote_currency=quote,
            rate=rate,
            rate_type="p2p",
            raw_payload=payload,
            fee_estimate=None,
            fee_currency=None,
        )

    def _result_from_option(
        self, payload: dict, option: dict, base: str, quote: str
    ) -> ScrapeResult:
        source_amount = self._parse_decimal(option.get("sourceAmount"), "sourceAmount")
        target_amount = self._parse_decimal(option.get("targetAmount"), "targetAmount")
        if source_amount <= 0:
            raise ScraperError(f"wise: non-positive sourceAmount {source_amount}")
        effective_rate = (target_amount / source_amount).quantize(Decimal("0.00000001"))
        if base == "CNY" and quote == "MYR":
            self._sanity_check(effective_rate)

        fee_total: Decimal | None = None
        fee = option.get("fee")
        if isinstance(fee, dict) and fee.get("total") is not None:
            try:
                fee_total = to_decimal(fee.get("total"))
            except Exception as exc:
                raise ScraperError(f"wise: cannot parse fee: {exc}") from exc

        return ScrapeResult(
            base_currency=base,
            quote_currency=quote,
            rate=effective_rate,
            rate_type="p2p",
            raw_payload=payload,
            fee_estimate=fee_total,
            fee_currency=base if fee_total is not None else None,
        )

    def _select_option(self, payload: dict) -> dict | None:
        options = payload.get("paymentOptions")
        if not isinstance(options, list) or not options:
            return None
        usable = [o for o in options if isinstance(o, dict) and not o.get("disabled", False)]
        if not usable:
            usable = [o for o in options if isinstance(o, dict)]
        if not usable:
            return None
        # Prefer BANK_TRANSFER both ways — that's the cheapest typical path.
        for o in usable:
            if (
                o.get("payIn") == self.PREFERRED_PAY_IN
                and o.get("payOut") == self.PREFERRED_PAY_OUT
            ):
                return o

        # Otherwise pick the lowest-fee option (with fallback for missing fees).
        def _fee_of(o: dict) -> Decimal:
            fee = o.get("fee")
            if isinstance(fee, dict) and fee.get("total") is not None:
                try:
                    return to_decimal(fee.get("total"))
                except Exception:
                    return Decimal("9" * 12)
            return Decimal("9" * 12)

        return min(usable, key=_fee_of)

    async def _request_quote(self, client: httpx.AsyncClient, *, source: str, target: str) -> dict:
        request_payload = {
            "sourceCurrency": source,
            "targetCurrency": target,
            "sourceAmount": self.REFERENCE_SOURCE_AMOUNT,
        }
        try:
            resp = await client.post(self.BASE_URL, json=request_payload)
            resp.raise_for_status()
            payload = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ScraperError(f"wise: HTTP error: {exc}") from exc
        if not isinstance(payload, dict):
            raise ScraperError(f"wise: expected object response, got {type(payload).__name__}")
        return payload

    async def _fetch_reverse_pair(
        self, client: httpx.AsyncClient, base: str, quote: str, reason: str
    ) -> ScrapeResult:
        reverse_payload = await self._request_quote(client, source=quote, target=base)
        rev_rate = reverse_payload.get("rate")
        if rev_rate is None:
            raise ScraperError(
                f"wise: primary failed ({reason}); reverse missing rate: {reverse_payload!r}"
            )
        rev = self._parse_decimal(rev_rate, "reverse rate")
        if rev == 0:
            raise ScraperError("wise: reverse rate is zero")
        rate = (Decimal("1") / rev).quantize(Decimal("0.00000001"))
        if base == "CNY" and quote == "MYR":
            self._sanity_check(rate)
        return ScrapeResult(
            base_currency=base,
            quote_currency=quote,
            rate=rate,
            rate_type="p2p",
            raw_payload={
                "fallback": "reverse_pair",
                "primary_error": reason,
                "reverse_payload": reverse_payload,
            },
            fee_estimate=None,
            fee_currency=None,
        )

    def _parse_decimal(self, value: object, what: str) -> Decimal:
        try:
            return to_decimal(value)
        except Exception as exc:
            raise ScraperError(f"wise: cannot parse {what}: {exc}") from exc
