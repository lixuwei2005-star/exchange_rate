from __future__ import annotations

from decimal import Decimal

import httpx
import pytest
import respx

from app.scrapers.base import ScraperError
from app.scrapers.wise import WiseScraper

WISE_URL = "https://api.wise.com/v3/quotes"


def quote_payload(
    *,
    rate: float | None = 0.585994,
    payment_options: list[dict] | None = None,
    source_currency: str = "CNY",
    target_currency: str = "MYR",
) -> dict:
    payload = {
        "sourceAmount": 1000.00,
        "guaranteedTargetAmountAllowed": False,
        "targetAmountAllowed": True,
        "paymentOptions": payment_options if payment_options is not None else bank_fee_options(),
        "rateTimestamp": "2026-05-28T03:23:51Z",
        "clientId": "unknown",
        "rateExpirationTime": "2026-05-29T03:24:45Z",
        "guaranteedTargetAmount": False,
        "providedAmountType": "SOURCE",
        "createdTime": "2026-05-28T03:24:45Z",
        "rateType": "FIXED",
        "payOut": "BANK_TRANSFER",
        "funding": "POST",
        "expirationTime": "2026-05-28T03:54:45Z",
        "sourceCurrency": source_currency,
        "targetCurrency": target_currency,
        "status": "PENDING",
        "type": "REGULAR",
    }
    if rate is not None:
        payload["rate"] = rate
    return payload


def bank_fee_options() -> list[dict]:
    return [
        {
            "formattedEstimatedDelivery": "in seconds",
            "payOut": "BANK_TRANSFER",
            "payIn": "ALIPAY",
            "price": {
                "total": {
                    "type": "TOTAL",
                    "label": "Total fees",
                    "value": {"amount": 10.34, "currency": "CNY", "label": "10.34 CNY"},
                }
            },
            "fee": {
                "transferwise": 10.34,
                "payIn": 0.0,
                "discount": 0,
                "total": 10.34,
                "priceSetId": 5129,
                "partner": 0.0,
            },
        },
        {
            "formattedEstimatedDelivery": "in 60 minutes",
            "payOut": "BANK_TRANSFER",
            "payIn": "BANK_TRANSFER",
            "price": {
                "total": {
                    "type": "TOTAL",
                    "label": "Total fees",
                    "value": {"amount": 25.66, "currency": "CNY", "label": "25.66 CNY"},
                }
            },
            "fee": {
                "transferwise": 25.66,
                "payIn": 0.0,
                "discount": 0,
                "total": 25.66,
                "priceSetId": 5102,
                "partner": 0.0,
            },
            "sourceAmount": 1000.00,
            "targetAmount": 570.96,
            "sourceCurrency": "CNY",
            "targetCurrency": "MYR",
        },
    ]


@pytest.mark.asyncio
@respx.mock
async def test_wise_parses_rate_and_preferred_bank_transfer_fee():
    route = respx.post(WISE_URL).mock(return_value=httpx.Response(200, json=quote_payload()))

    result = await WiseScraper().fetch("CNY", "MYR")

    assert result.rate == Decimal("0.585994")
    assert result.fee_estimate == Decimal("25.66")
    assert result.fee_currency == "CNY"
    assert result.rate_type == "p2p"
    assert result.raw_payload["rate"] == 0.585994
    assert route.calls[0].request.url.path == "/v3/quotes"


@pytest.mark.asyncio
@respx.mock
async def test_wise_uses_lowest_fee_when_bank_transfer_combo_absent():
    payment_options = [
        {
            "payIn": "ALIPAY",
            "payOut": "BANK_TRANSFER",
            "price": {
                "total": {"value": {"amount": 38.55, "currency": "CNY", "label": "38.55 CNY"}}
            },
            "fee": {"total": 38.55},
        },
        {
            "payIn": "CARD",
            "payOut": "BANK_TRANSFER",
            "price": {
                "total": {"value": {"amount": 42.12, "currency": "CNY", "label": "42.12 CNY"}}
            },
            "fee": {"total": 42.12},
        },
    ]
    respx.post(WISE_URL).mock(
        return_value=httpx.Response(200, json=quote_payload(payment_options=payment_options))
    )

    result = await WiseScraper().fetch("CNY", "MYR")

    assert result.fee_estimate == Decimal("38.55")
    assert result.fee_currency == "CNY"


@pytest.mark.asyncio
@respx.mock
async def test_wise_rejects_out_of_range_rate():
    respx.post(WISE_URL).mock(return_value=httpx.Response(200, json=quote_payload(rate=0.9)))

    with pytest.raises(ScraperError):
        await WiseScraper().fetch("CNY", "MYR")


@pytest.mark.asyncio
@respx.mock
async def test_wise_empty_payment_options_keeps_primary_rate_without_fee():
    respx.post(WISE_URL).mock(
        return_value=httpx.Response(200, json=quote_payload(payment_options=[]))
    )

    result = await WiseScraper().fetch("CNY", "MYR")

    assert result.rate == Decimal("0.585994")
    assert result.fee_estimate is None
    assert result.fee_currency is None


@pytest.mark.asyncio
@respx.mock
async def test_wise_reverse_pair_contingency_when_empty_options_have_no_rate():
    primary = quote_payload(rate=None, payment_options=[])
    reverse = quote_payload(
        rate=1.7065,
        payment_options=[],
        source_currency="MYR",
        target_currency="CNY",
    )
    respx.post(WISE_URL).mock(
        side_effect=[
            httpx.Response(200, json=primary),
            httpx.Response(200, json=reverse),
        ]
    )

    result = await WiseScraper().fetch("CNY", "MYR")

    assert result.rate == Decimal("1") / Decimal("1.7065")
    assert result.fee_estimate is None
    assert result.fee_currency is None
    assert result.raw_payload["fallback"] == "reverse_pair"
