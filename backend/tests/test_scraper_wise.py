from __future__ import annotations

from decimal import Decimal

import httpx
import pytest
import respx

from app.scrapers.base import ScraperError
from app.scrapers.wise import WiseScraper


@pytest.mark.asyncio
@respx.mock
async def test_wise_happy_path_array():
    respx.get("https://api.wise.com/v1/rates", params={"source": "CNY", "target": "MYR"}).mock(
        return_value=httpx.Response(
            200, json=[{"source": "CNY", "target": "MYR", "rate": 0.6582, "time": "..."}]
        )
    )
    r = await WiseScraper().fetch("CNY", "MYR")
    assert r.rate == Decimal("0.6582")
    assert r.rate_type == "p2p"


@pytest.mark.asyncio
@respx.mock
async def test_wise_happy_path_object():
    respx.get("https://api.wise.com/v1/rates").mock(
        return_value=httpx.Response(200, json={"rate": 0.6512})
    )
    r = await WiseScraper().fetch("CNY", "MYR")
    assert r.rate == Decimal("0.6512")


@pytest.mark.asyncio
@respx.mock
async def test_wise_missing_rate():
    respx.get("https://api.wise.com/v1/rates").mock(
        return_value=httpx.Response(200, json={"other": "junk"})
    )
    with pytest.raises(ScraperError):
        await WiseScraper().fetch("CNY", "MYR")
