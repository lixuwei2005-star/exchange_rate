"""Visa scraper tests.

The network half (curl_cffi → cmsapi) is hard to mock cleanly because
respx targets httpx. The parser is the interesting part: Visa's API
silently swaps from/to, so we have to trust `originalValues.fromCurrency`
and invert when the response's direction is opposite of what we asked.
All tests below exercise the pure parser via `VisaScraper()._parse(...)`.

No issuer markup is applied — homepage shows pure channel rates only
(CLAUDE.md §6).
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.scrapers.base import ScraperError
from app.scrapers.visa import VisaScraper


def _payload(ov: dict) -> dict:
    """Wrap an originalValues dict in the outer shape Visa returns."""
    return {"originalValues": ov, "status": "success"}


def test_visa_parser_natural_direction():
    """When originalValues already says from=CNY to=MYR, take fxRateVisa
    directly without inverting and without applying any markup."""
    payload = _payload(
        {
            "fromCurrency": "CNY",
            "toCurrency": "MYR",
            "fxRateVisa": "0.5857051892",
            "asOfDate": 1779926400,
            "lastUpdatedVisaRate": 1779925825,
        }
    )

    r = VisaScraper()._parse(payload, base="CNY", quote="MYR")

    # Quantized to 8 places — no markup applied.
    assert r.rate == Decimal("0.58570519")
    assert Decimal("0.5") <= r.rate <= Decimal("0.8")
    assert r.rate_type == "card_network"
    assert r.fee_estimate is None
    assert r.fee_currency is None
    assert r.raw_payload["direction"] == "natural"
    assert r.raw_payload["ov_from"] == "CNY"
    assert r.raw_payload["ov_to"] == "MYR"
    assert r.raw_payload["last_updated_visa_rate"] == 1779925825


def test_visa_parser_inverted_direction():
    """Visa's known quirk: when we ask CNY -> MYR, the API may respond with
    originalValues.fromCurrency=MYR, toCurrency=CNY and fxRateVisa expressed
    as MYR-per-CNY's inverse (1 MYR = 1.71 CNY). The parser must invert."""
    payload = _payload(
        {
            "fromCurrency": "MYR",
            "toCurrency": "CNY",
            "fxRateVisa": "1.7116421289",
        }
    )

    r = VisaScraper()._parse(payload, base="CNY", quote="MYR")

    # 1 / 1.7116421289 ≈ 0.58423428 (quantized to 8 places).
    assert r.rate == Decimal("0.58423428")
    assert Decimal("0.5") <= r.rate <= Decimal("0.8")
    assert r.raw_payload["direction"] == "inverted"


def test_visa_parser_rejects_unrelated_currency_pair():
    """If originalValues comes back with totally different currencies,
    bail loud rather than silently using a wrong rate."""
    payload = _payload({"fromCurrency": "EUR", "toCurrency": "USD", "fxRateVisa": "1.0800"})

    with pytest.raises(ScraperError, match="unexpected pair"):
        VisaScraper()._parse(payload, base="CNY", quote="MYR")


def test_visa_parser_raises_when_original_values_missing():
    with pytest.raises(ScraperError, match="missing originalValues"):
        VisaScraper()._parse({"status": "success"}, base="CNY", quote="MYR")


def test_visa_parser_raises_when_fx_rate_missing():
    payload = _payload({"fromCurrency": "CNY", "toCurrency": "MYR"})
    with pytest.raises(ScraperError, match="fxRateVisa missing"):
        VisaScraper()._parse(payload, base="CNY", quote="MYR")


def test_visa_parser_raises_on_negative_rate():
    payload = _payload({"fromCurrency": "CNY", "toCurrency": "MYR", "fxRateVisa": "-0.5"})
    with pytest.raises(ScraperError, match="non-positive"):
        VisaScraper()._parse(payload, base="CNY", quote="MYR")


def test_visa_parser_raises_on_unparseable_rate():
    payload = _payload({"fromCurrency": "CNY", "toCurrency": "MYR", "fxRateVisa": "not-a-number"})
    with pytest.raises(ScraperError, match="cannot parse fxRateVisa"):
        VisaScraper()._parse(payload, base="CNY", quote="MYR")


def test_visa_parser_raises_on_out_of_range_rate():
    """Sanity check: if a future Visa payload accidentally gave us a rate
    outside the CNY->MYR [0.5, 0.8] band, bail rather than store it."""
    payload = _payload({"fromCurrency": "CNY", "toCurrency": "MYR", "fxRateVisa": "2.5"})
    with pytest.raises(ScraperError, match="sanity check failed"):
        VisaScraper()._parse(payload, base="CNY", quote="MYR")


@pytest.mark.asyncio
async def test_visa_rejects_non_myr_quote():
    with pytest.raises(ScraperError, match="only MYR"):
        await VisaScraper().fetch("CNY", "USD")


@pytest.mark.asyncio
async def test_visa_rejects_non_cny_base():
    with pytest.raises(ScraperError, match="only CNY base"):
        await VisaScraper().fetch("USD", "MYR")
