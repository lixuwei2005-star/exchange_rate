"""Secondary midmarket (api.exchangerate.fun) scraper tests.

Same `{rates: {CCY: value}}` shape as Frankfurter; tests focus on the
parser's defense in depth: missing rates, missing currency, base echo
mismatch, sanity-range failure.
"""

from __future__ import annotations

from decimal import Decimal

import httpx
import pytest
import respx

from app.scrapers.base import ScraperError
from app.scrapers.midmarket2 import Midmarket2Scraper

URL = "https://api.exchangerate.fun/latest"


@pytest.mark.asyncio
@respx.mock
async def test_midmarket2_takes_rates_myr_directly():
    respx.get(URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "timestamp": 1779973200,
                "base": "CNY",
                "rates": {"MYR": 0.586818, "USD": 0.147512, "EUR": 0.126765},
            },
        )
    )

    r = await Midmarket2Scraper().fetch("CNY", "MYR")

    # 0.586818 quantized to 8 decimal places.
    assert r.rate == Decimal("0.58681800")
    assert Decimal("0.5") <= r.rate <= Decimal("0.8")
    assert r.rate_type == "midmarket"
    assert r.fee_estimate is None
    assert r.raw_payload["base"] == "CNY"
    assert r.raw_payload["timestamp"] == 1779973200


def test_midmarket2_parser_rejects_base_mismatch():
    """If the API silently falls back to USD when we asked for CNY,
    `rates.MYR` would be MYR-per-USD not MYR-per-CNY — would store a
    wildly wrong rate. Bail loud."""
    payload = {"base": "USD", "rates": {"MYR": 3.9781}}
    with pytest.raises(ScraperError, match="response.base="):
        Midmarket2Scraper()._parse(payload, base="CNY", quote="MYR")


def test_midmarket2_parser_raises_when_rates_missing():
    payload = {"base": "CNY"}
    with pytest.raises(ScraperError, match="missing rates dict"):
        Midmarket2Scraper()._parse(payload, base="CNY", quote="MYR")


def test_midmarket2_parser_raises_when_quote_missing():
    payload = {"base": "CNY", "rates": {"USD": 0.14}}
    with pytest.raises(ScraperError, match="missing rates.MYR"):
        Midmarket2Scraper()._parse(payload, base="CNY", quote="MYR")


def test_midmarket2_parser_raises_on_non_dict_payload():
    with pytest.raises(ScraperError, match="not a JSON object"):
        Midmarket2Scraper()._parse("oops", base="CNY", quote="MYR")


def test_midmarket2_parser_raises_on_non_positive_rate():
    payload = {"base": "CNY", "rates": {"MYR": 0}}
    with pytest.raises(ScraperError, match="non-positive"):
        Midmarket2Scraper()._parse(payload, base="CNY", quote="MYR")


def test_midmarket2_parser_raises_on_out_of_range_rate():
    """If MYR rate ever lands outside [0.5, 0.8] for CNY base, the sanity
    check in Scraper._sanity_check trips. Defensive — the upstream is a
    free API and could glitch."""
    payload = {"base": "CNY", "rates": {"MYR": 5.0}}
    with pytest.raises(ScraperError, match="sanity check failed"):
        Midmarket2Scraper()._parse(payload, base="CNY", quote="MYR")


@pytest.mark.asyncio
@respx.mock
async def test_midmarket2_raises_on_http_error():
    respx.get(URL).mock(return_value=httpx.Response(500, text="server error"))
    with pytest.raises(ScraperError, match="HTTP error"):
        await Midmarket2Scraper().fetch("CNY", "MYR")
