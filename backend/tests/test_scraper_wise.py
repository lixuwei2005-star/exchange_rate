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
    """Two-option set matching the real Wise response shape: an ALIPAY→BANK
    cheap option and the BANK→BANK option we prefer (slightly higher fee)."""
    return [
        {
            "formattedEstimatedDelivery": "in seconds",
            "payOut": "BANK_TRANSFER",
            "payIn": "ALIPAY",
            "sourceAmount": 1000.00,
            "targetAmount": 580.04,
            "sourceCurrency": "CNY",
            "targetCurrency": "MYR",
            "price": {
                "total": {
                    "type": "TOTAL",
                    "label": "Total fees",
                    "value": {"amount": 10.34, "currency": "CNY", "label": "10.34 CNY"},
                }
            },
            "fee": {"total": 10.34},
        },
        {
            "formattedEstimatedDelivery": "in 60 minutes",
            "payOut": "BANK_TRANSFER",
            "payIn": "BANK_TRANSFER",
            "sourceAmount": 1000.00,
            "targetAmount": 570.96,
            "sourceCurrency": "CNY",
            "targetCurrency": "MYR",
            "price": {
                "total": {
                    "type": "TOTAL",
                    "label": "Total fees",
                    "value": {"amount": 25.66, "currency": "CNY", "label": "25.66 CNY"},
                }
            },
            "fee": {"total": 25.66},
        },
    ]


@pytest.mark.asyncio
@respx.mock
async def test_wise_stores_effective_rate_from_preferred_bank_transfer_option():
    """rate = targetAmount/sourceAmount on the BANK→BANK option,
    NOT the top-level mid-market `rate` field."""
    route = respx.post(WISE_URL).mock(return_value=httpx.Response(200, json=quote_payload()))

    result = await WiseScraper().fetch("CNY", "MYR")

    # 570.96 / 1000 = 0.57096 — the effective rate after Wise's fee
    assert result.rate == (Decimal("570.96") / Decimal("1000")).quantize(Decimal("0.00000001"))
    # NOT the mid-market 0.585994 (which is bigger)
    assert result.rate < Decimal("0.585994")
    assert result.fee_estimate == Decimal("25.66")
    assert result.fee_currency == "CNY"
    assert result.rate_type == "p2p"
    assert route.calls[0].request.url.path == "/v3/quotes"


@pytest.mark.asyncio
@respx.mock
async def test_wise_falls_back_to_lowest_fee_when_bank_transfer_combo_absent():
    payment_options = [
        {
            "payIn": "ALIPAY",
            "payOut": "BANK_TRANSFER",
            "sourceAmount": 1000.00,
            "targetAmount": 565.10,
            "price": {
                "total": {"value": {"amount": 38.55, "currency": "CNY", "label": "38.55 CNY"}}
            },
            "fee": {"total": 38.55},
        },
        {
            "payIn": "CARD",
            "payOut": "BANK_TRANSFER",
            "sourceAmount": 1000.00,
            "targetAmount": 560.00,
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

    assert result.fee_estimate == Decimal("38.55")  # lowest fee option chosen
    assert result.rate == (Decimal("565.10") / Decimal("1000")).quantize(Decimal("0.00000001"))


@pytest.mark.asyncio
@respx.mock
async def test_wise_rejects_out_of_range_effective_rate():
    # craft an option whose effective rate falls outside the [0.5, 0.8] window
    bad_options = [
        {
            "payIn": "BANK_TRANSFER",
            "payOut": "BANK_TRANSFER",
            "sourceAmount": 1000.00,
            "targetAmount": 100.00,  # → 0.1, way too low
            "fee": {"total": 5.0},
            "price": {"total": {"value": {"currency": "CNY"}}},
        }
    ]
    respx.post(WISE_URL).mock(
        return_value=httpx.Response(200, json=quote_payload(payment_options=bad_options))
    )

    with pytest.raises(ScraperError):
        await WiseScraper().fetch("CNY", "MYR")


@pytest.mark.asyncio
@respx.mock
async def test_wise_empty_payment_options_falls_back_to_top_level_rate():
    """When paymentOptions is empty, fall back to the response's top-level
    mid-market `rate` (no fee info, less accurate but better than failing)."""
    respx.post(WISE_URL).mock(
        return_value=httpx.Response(200, json=quote_payload(payment_options=[]))
    )

    result = await WiseScraper().fetch("CNY", "MYR")

    assert result.rate == Decimal("0.585994")
    assert result.fee_estimate is None
    assert result.fee_currency is None


@pytest.mark.asyncio
@respx.mock
async def test_wise_quote_for_amount_returns_on_demand_quote():
    """quote_for_amount sends the user's actual amount to Wise so the fee
    column on the homepage reflects reality (Wise's fee is fixed + variable,
    so it's NOT proportional to amount)."""
    # Wise quote at sourceAmount=500 → returns 22.47 CNY fee for that amount
    custom_options = [
        {
            "payIn": "BANK_TRANSFER",
            "payOut": "BANK_TRANSFER",
            "sourceAmount": 500.00,
            "targetAmount": 282.65,
            "sourceCurrency": "CNY",
            "targetCurrency": "MYR",
            "fee": {"total": 22.47},
        },
    ]
    respx.post(WISE_URL).mock(
        return_value=httpx.Response(200, json=quote_payload(payment_options=custom_options))
    )

    result = await WiseScraper().quote_for_amount("CNY", "MYR", 500)
    assert result["source_amount"] == Decimal("500.00")
    assert result["target_amount"] == Decimal("282.65")
    assert result["fee"] == Decimal("22.47")
    assert result["fee_currency"] == "CNY"
    expected_rate = (Decimal("282.65") / Decimal("500.00")).quantize(Decimal("0.00000001"))
    assert result["rate"] == expected_rate


@pytest.mark.asyncio
@respx.mock
async def test_wise_reverse_pair_contingency_when_primary_http_fails():
    reverse = quote_payload(
        rate=1.7065,
        payment_options=[],
        source_currency="MYR",
        target_currency="CNY",
    )
    respx.post(WISE_URL).mock(
        side_effect=[
            httpx.Response(500),  # primary blows up
            httpx.Response(200, json=reverse),
        ]
    )

    result = await WiseScraper().fetch("CNY", "MYR")

    assert result.rate == (Decimal("1") / Decimal("1.7065")).quantize(Decimal("0.00000001"))
    assert result.fee_estimate is None
    assert result.fee_currency is None
    assert result.raw_payload["fallback"] == "reverse_pair"
