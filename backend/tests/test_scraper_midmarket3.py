"""exchangerate-api.com v6 scraper tests.

The shape is similar to Frankfurter / exchangerate.fun but the rates dict
is named `conversion_rates` and there's a top-level `result` discriminator.
The scraper also short-circuits when EXCHANGERATE_API_KEY is empty so the
free-tier quota isn't burned on bad calls.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch

import httpx
import pytest
import respx

from app.config import Settings, get_settings
from app.scrapers.base import ScraperError
from app.scrapers.midmarket3 import Midmarket3Scraper

# The fetch() URL embeds the key in the path. Tests use a fixture key.
FIXTURE_KEY = "test-key-123"
URL = f"https://v6.exchangerate-api.com/v6/{FIXTURE_KEY}/latest/CNY"


@pytest.fixture(autouse=True)
def _patch_settings():
    """Inject a fake api key into get_settings() for every test."""
    fake = Settings(
        fernet_key="jXV6ArgMcNyfMYx2bl6w2BQZtNsraEP2W0hs0HAVB6I=",
        jwt_secret="test-jwt-secret-padded-to-be-long-enough-for-hs256",
        exchangerate_api_key=FIXTURE_KEY,
    )
    get_settings.cache_clear()
    with patch("app.scrapers.midmarket3.get_settings", return_value=fake):
        yield
    get_settings.cache_clear()


def _payload(rate_myr: float | str, *, result: str = "success", base: str = "CNY") -> dict:
    return {
        "result": result,
        "base_code": base,
        "time_last_update_unix": 1779926401,
        "time_last_update_utc": "Thu, 28 May 2026 00:00:01 +0000",
        "time_next_update_unix": 1780012801,
        "conversion_rates": {"MYR": rate_myr, "USD": 0.1472},
    }


@pytest.mark.asyncio
@respx.mock
async def test_midmarket3_takes_conversion_rates_myr_directly():
    respx.get(URL).mock(return_value=httpx.Response(200, json=_payload(0.5831)))

    r = await Midmarket3Scraper().fetch("CNY", "MYR")

    assert r.rate == Decimal("0.58310000")
    assert Decimal("0.5") <= r.rate <= Decimal("0.8")
    assert r.rate_type == "midmarket"
    assert r.fee_estimate is None
    assert r.raw_payload["base_code"] == "CNY"
    assert r.raw_payload["time_last_update_unix"] == 1779926401
    assert r.raw_payload["result"] == "success"


def test_midmarket3_parser_rejects_non_success_result():
    payload = _payload(0.5831, result="error")
    payload["error-type"] = "invalid-key"
    with pytest.raises(ScraperError, match="result='error'.*invalid-key"):
        Midmarket3Scraper()._parse(payload, base="CNY", quote="MYR")


def test_midmarket3_parser_rejects_base_mismatch():
    """If the API ever silently falls back to USD, conversion_rates.MYR
    would be MYR-per-USD rather than MYR-per-CNY — wildly wrong."""
    payload = _payload(3.965, base="USD")
    with pytest.raises(ScraperError, match="base_code='USD'"):
        Midmarket3Scraper()._parse(payload, base="CNY", quote="MYR")


def test_midmarket3_parser_raises_when_conversion_rates_missing():
    with pytest.raises(ScraperError, match="missing conversion_rates"):
        Midmarket3Scraper()._parse(
            {"result": "success", "base_code": "CNY"}, base="CNY", quote="MYR"
        )


def test_midmarket3_parser_raises_when_quote_missing():
    payload = _payload(0.5831)
    payload["conversion_rates"] = {"USD": 0.14}  # no MYR
    with pytest.raises(ScraperError, match="conversion_rates.MYR missing"):
        Midmarket3Scraper()._parse(payload, base="CNY", quote="MYR")


def test_midmarket3_parser_raises_on_non_dict_payload():
    with pytest.raises(ScraperError, match="not a JSON object"):
        Midmarket3Scraper()._parse("oops", base="CNY", quote="MYR")


def test_midmarket3_parser_raises_on_zero_rate():
    with pytest.raises(ScraperError, match="non-positive"):
        Midmarket3Scraper()._parse(_payload(0), base="CNY", quote="MYR")


def test_midmarket3_parser_raises_on_out_of_range_rate():
    with pytest.raises(ScraperError, match="sanity check failed"):
        Midmarket3Scraper()._parse(_payload(5.0), base="CNY", quote="MYR")


@pytest.mark.asyncio
@respx.mock
async def test_midmarket3_raises_on_http_error():
    respx.get(URL).mock(return_value=httpx.Response(500, text="server error"))
    with pytest.raises(ScraperError, match="HTTP error"):
        await Midmarket3Scraper().fetch("CNY", "MYR")


@pytest.mark.asyncio
async def test_midmarket3_short_circuits_when_key_empty():
    """No HTTP call should be made when the env key is empty — keeps the
    free-tier quota intact and gives admin a clear actionable error."""
    fake = Settings(
        fernet_key="jXV6ArgMcNyfMYx2bl6w2BQZtNsraEP2W0hs0HAVB6I=",
        jwt_secret="test-jwt-secret-padded-to-be-long-enough-for-hs256",
        exchangerate_api_key="",
    )
    with patch("app.scrapers.midmarket3.get_settings", return_value=fake):
        with pytest.raises(ScraperError, match="EXCHANGERATE_API_KEY is not set"):
            await Midmarket3Scraper().fetch("CNY", "MYR")
