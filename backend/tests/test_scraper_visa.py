from __future__ import annotations

from decimal import Decimal

import httpx
import pytest
import respx

from app.scrapers.visa import VISA_ISSUER_MARKUP, VisaScraper


@pytest.mark.asyncio
@respx.mock
async def test_visa_applies_issuer_markup():
    respx.get("https://www.visa.com.my/cmsapi/fx/rates").mock(
        return_value=httpx.Response(
            200,
            json={
                "originalValues": {
                    "fxRate": "0.6700",
                    "fromCurrency": "CNY",
                    "toCurrency": "MYR",
                }
            },
        )
    )
    r = await VisaScraper().fetch("CNY", "MYR")
    expected = (Decimal("0.6700") * (Decimal("1") - VISA_ISSUER_MARKUP)).quantize(
        Decimal("0.00000001")
    )
    assert r.rate == expected
    assert r.rate_type == "card_network"
