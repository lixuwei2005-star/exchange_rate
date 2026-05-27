from __future__ import annotations

from decimal import Decimal

import httpx
import pytest
import respx

from app.scrapers.base import ScraperError
from app.scrapers.midmarket import MidmarketScraper


@pytest.mark.asyncio
@respx.mock
async def test_midmarket_happy_path():
    respx.get("https://api.frankfurter.dev/v1/latest", params={"from": "CNY", "to": "MYR"}).mock(
        return_value=httpx.Response(
            200,
            json={
                "amount": 1.0,
                "base": "CNY",
                "date": "2026-05-27",
                "rates": {"MYR": 0.6582},
            },
        )
    )
    r = await MidmarketScraper().fetch("CNY", "MYR")
    assert r.rate == Decimal("0.6582")
    assert r.rate_type == "midmarket"
    assert r.base_currency == "CNY"
    assert r.quote_currency == "MYR"
    assert r.raw_payload["rates"]["MYR"] == 0.6582


@pytest.mark.asyncio
@respx.mock
async def test_midmarket_rejects_out_of_range_rate():
    respx.get("https://api.frankfurter.dev/v1/latest", params={"from": "CNY", "to": "MYR"}).mock(
        return_value=httpx.Response(
            200,
            json={"amount": 1.0, "base": "CNY", "date": "2026-05-27", "rates": {"MYR": 99.9}},
        )
    )
    with pytest.raises(ScraperError):
        await MidmarketScraper().fetch("CNY", "MYR")


@pytest.mark.asyncio
@respx.mock
async def test_midmarket_propagates_http_error():
    respx.get("https://api.frankfurter.dev/v1/latest").mock(return_value=httpx.Response(500))
    with pytest.raises(ScraperError):
        await MidmarketScraper().fetch("CNY", "MYR")


@pytest.mark.asyncio
@respx.mock
async def test_midmarket_missing_quote_in_response():
    respx.get("https://api.frankfurter.dev/v1/latest").mock(
        return_value=httpx.Response(
            200,
            json={"amount": 1.0, "base": "CNY", "date": "2026-05-27", "rates": {}},
        )
    )
    with pytest.raises(ScraperError):
        await MidmarketScraper().fetch("CNY", "MYR")
