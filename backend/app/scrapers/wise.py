from __future__ import annotations

from decimal import Decimal
from typing import ClassVar

import httpx

from app.scrapers._common import make_client, to_decimal
from app.scrapers.base import Scraper, ScraperError, ScrapeResult


class WiseScraper(Scraper):
    """Wise unauthenticated quote endpoint.

    Wise returns rate as quote per 1 source, exactly the direction we store
    for CNY->MYR. Fees are captured from a 1000-source-currency reference quote.
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

            rate_value = payload.get("rate")
            if rate_value is None and payload.get("paymentOptions") == []:
                return await self._fetch_reverse_pair(
                    client, base, quote, "primary quote had empty paymentOptions and no rate"
                )
            if rate_value is None:
                raise ScraperError(f"wise: response missing rate: {payload!r}")

            rate = self._parse_rate(rate_value)
            if base == "CNY" and quote == "MYR":
                self._sanity_check(rate)

            fee_estimate, fee_currency = self._extract_fee(payload, source_currency=base)
            return ScrapeResult(
                base_currency=base,
                quote_currency=quote,
                rate=rate,
                rate_type="p2p",
                raw_payload=payload,
                fee_estimate=fee_estimate,
                fee_currency=fee_currency,
            )

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
        reverse_rate_value = reverse_payload.get("rate")
        if reverse_rate_value is None:
            raise ScraperError(
                f"wise: primary quote failed ({reason}); reverse response missing rate: "
                f"{reverse_payload!r}"
            )

        reverse_rate = self._parse_rate(reverse_rate_value)
        if reverse_rate == 0:
            raise ScraperError("wise: reverse response rate is zero")
        rate = Decimal("1") / reverse_rate

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

    def _parse_rate(self, value: object) -> Decimal:
        try:
            return to_decimal(value)
        except Exception as exc:
            raise ScraperError(f"wise: cannot parse rate: {exc}") from exc

    def _extract_fee(
        self, payload: dict, *, source_currency: str
    ) -> tuple[Decimal | None, str | None]:
        options = payload.get("paymentOptions")
        if not isinstance(options, list) or not options:
            return None, None

        fee_options: list[tuple[dict, Decimal]] = []
        for option in options:
            if not isinstance(option, dict):
                continue
            fee = option.get("fee")
            if not isinstance(fee, dict) or fee.get("total") is None:
                continue
            try:
                fee_options.append((option, to_decimal(fee.get("total"))))
            except Exception as exc:
                raise ScraperError(f"wise: cannot parse fee: {exc}") from exc

        if not fee_options:
            return None, None

        selected_option, fee_total = self._select_fee_option(fee_options)
        fee_currency = self._extract_fee_currency(selected_option, source_currency=source_currency)
        return fee_total, fee_currency

    def _select_fee_option(self, fee_options: list[tuple[dict, Decimal]]) -> tuple[dict, Decimal]:
        for option, fee_total in fee_options:
            if (
                option.get("payIn") == self.PREFERRED_PAY_IN
                and option.get("payOut") == self.PREFERRED_PAY_OUT
            ):
                return option, fee_total
        return min(fee_options, key=lambda item: item[1])

    def _extract_fee_currency(self, option: dict, *, source_currency: str) -> str:
        price = option.get("price")
        currency = None
        if isinstance(price, dict):
            total = price.get("total")
            if isinstance(total, dict):
                value = total.get("value")
                if isinstance(value, dict):
                    currency = value.get("currency")

        if currency is None:
            return source_currency
        if currency != source_currency:
            raise ScraperError(
                f"wise: fee currency {currency!r} does not match source {source_currency!r}"
            )
        return source_currency
