from __future__ import annotations

from decimal import Decimal

import httpx
import pytest
import respx

from app.scrapers.mastercard import MastercardScraper


@pytest.mark.asyncio
@respx.mock
async def test_mastercard_stores_pure_network_rate():
    respx.get("https://www.mastercard.us/settlement/currencyrate/conversion-rate").mock(
        return_value=httpx.Response(200, json={"data": {"conversionRate": "0.6655"}})
    )
    r = await MastercardScraper().fetch("CNY", "MYR")
    assert r.rate == Decimal("0.6655").quantize(Decimal("0.00000001"))
    assert r.rate_type == "card_network"
