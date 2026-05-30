"""Affin Bank Malaysia scraper tests.

Affin publishes static JSON feeds. The per-100-unit feed holds CNY:

    {"currency": "CHINESE RENMINBI", "code": "(CNY)",
     "selling": {"ttod": 60.6}, "buying": {"tt": 56.6, "od": "N/A"}}

For CNY -> MYR we take buying.tt ÷ 100 (bank buys CNY). buying.od is "N/A"
for CNY and ignored.
"""

from __future__ import annotations

from decimal import Decimal

import httpx
import pytest
import respx

from app.scrapers.affin import AffinScraper
from app.scrapers.base import ScraperError


def _entry(tt, od="N/A", ttod=60.6, code="(CNY)", name="CHINESE RENMINBI") -> dict:
    return {
        "currency": name,
        "code": code,
        "selling": {"ttod": ttod},
        "buying": {"tt": tt, "od": od},
    }


LIVE = [
    {
        "currency": "U.S.DOLLAR",
        "code": "(USD)",
        "selling": {"ttod": 4.075},
        "buying": {"tt": 3.865, "od": 3.855},
    },
    _entry(56.6),
    {
        "currency": "EURO",
        "code": "(EUR)",
        "selling": {"ttod": 4.9},
        "buying": {"tt": 4.45, "od": 4.42},
    },
]
DATEFEED = [{"date": "EXCHANGE RATE AS AT  29-May-26 TIME : 8:43 AM"}]


@pytest.mark.asyncio
@respx.mock
async def test_affin_picks_cny_buying_tt_and_divides_by_100():
    respx.get(AffinScraper.URL).mock(return_value=httpx.Response(200, json=LIVE))
    respx.get(AffinScraper.DATE_URL).mock(return_value=httpx.Response(200, json=DATEFEED))

    r = await AffinScraper().fetch("CNY", "MYR")

    # 56.6 / 100 = 0.56600000
    assert r.rate == Decimal("0.56600000")
    assert Decimal("0.5") <= r.rate <= Decimal("0.8")
    assert r.rate_type == "tt_buy"
    assert r.fee_estimate is None
    assert r.raw_payload["buying_tt"] == "56.6"
    assert r.raw_payload["multiplier"] == 100
    assert r.raw_payload["code"] == "(CNY)"
    assert "29-May-26" in r.raw_payload["as_at"]


@pytest.mark.asyncio
@respx.mock
async def test_affin_works_when_date_feed_fails():
    """The timestamp feed is decorative — a failure there must not break us."""
    respx.get(AffinScraper.URL).mock(return_value=httpx.Response(200, json=LIVE))
    respx.get(AffinScraper.DATE_URL).mock(return_value=httpx.Response(500, text="err"))

    r = await AffinScraper().fetch("CNY", "MYR")
    assert r.rate == Decimal("0.56600000")
    assert r.raw_payload["as_at"] is None


def test_affin_parser_raises_when_tt_na():
    payload = [_entry("N/A")]
    with pytest.raises(ScraperError, match="unavailable"):
        AffinScraper()._parse(payload, base="CNY", quote="MYR")


def test_affin_parser_raises_when_cny_missing():
    payload = [{"currency": "EURO", "code": "(EUR)", "buying": {"tt": 4.45}}]
    with pytest.raises(ScraperError, match="no CNY entry"):
        AffinScraper()._parse(payload, base="CNY", quote="MYR")


def test_affin_parser_raises_on_non_list():
    with pytest.raises(ScraperError, match="expected a JSON list"):
        AffinScraper()._parse({"oops": 1}, base="CNY", quote="MYR")


def test_affin_parser_raises_on_out_of_range():
    # buying.tt 90 / 100 = 0.90 → above the [0.5, 0.8] band.
    with pytest.raises(ScraperError, match="sanity check failed"):
        AffinScraper()._parse([_entry(90)], base="CNY", quote="MYR")


@pytest.mark.asyncio
@respx.mock
async def test_affin_raises_on_http_error():
    respx.get(AffinScraper.URL).mock(return_value=httpx.Response(500, text="server error"))
    with pytest.raises(ScraperError, match="HTTP error"):
        await AffinScraper().fetch("CNY", "MYR")


@pytest.mark.asyncio
async def test_affin_rejects_non_myr_quote():
    with pytest.raises(ScraperError, match="only MYR"):
        await AffinScraper().fetch("CNY", "USD")


@pytest.mark.asyncio
async def test_affin_rejects_non_cny_base():
    with pytest.raises(ScraperError, match="only CNY base"):
        await AffinScraper().fetch("USD", "MYR")
