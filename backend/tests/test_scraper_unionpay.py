from __future__ import annotations

from decimal import Decimal

import httpx
import pytest
import respx

from app.scrapers.unionpay import UnionPayScraper


@pytest.mark.asyncio
@respx.mock
async def test_unionpay_inverts_response_to_myr_per_cny():
    # Response says "1 MYR = 1.65 CNY" → stored rate = 1/1.65 MYR/CNY
    respx.get("https://www.unionpayintl.com/upload/jfimg/exchangeRate.txt").mock(
        return_value=httpx.Response(
            200,
            json={"data": [{"transCur": "MYR", "exchangeRate": "1.65"}]},
        )
    )
    r = await UnionPayScraper().fetch("CNY", "MYR")
    expected = (Decimal("1") / Decimal("1.65")).quantize(Decimal("0.00000001"))
    assert r.rate == expected
    assert r.rate_type == "card_network"


@pytest.mark.asyncio
@respx.mock
async def test_unionpay_handles_simple_dict_shape():
    respx.get("https://www.unionpayintl.com/upload/jfimg/exchangeRate.txt").mock(
        return_value=httpx.Response(200, json={"MYR": "1.55"})
    )
    r = await UnionPayScraper().fetch("CNY", "MYR")
    assert r.rate == (Decimal("1") / Decimal("1.55")).quantize(Decimal("0.00000001"))
