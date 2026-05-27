from __future__ import annotations

from decimal import Decimal

import httpx
import pytest
import respx

from app.scrapers.mastercard import MASTERCARD_ISSUER_MARKUP, MastercardScraper


@pytest.mark.asyncio
@respx.mock
async def test_mastercard_applies_issuer_markup():
    respx.get("https://www.mastercard.us/settlement/currencyrate/conversion-rate").mock(
        return_value=httpx.Response(200, json={"data": {"conversionRate": "0.6655"}})
    )
    r = await MastercardScraper().fetch("CNY", "MYR")
    expected = (Decimal("0.6655") * (Decimal("1") - MASTERCARD_ISSUER_MARKUP)).quantize(
        Decimal("0.00000001")
    )
    assert r.rate == expected
    assert r.rate_type == "card_network"
