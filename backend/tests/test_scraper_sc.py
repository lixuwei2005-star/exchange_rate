"""Standard Chartered Malaysia scraper tests.

The FX board is one of several server-rendered tables on the deposits page.
Header (whitespace-collapsed in the DOM):

    UNIT | CURRENCY | SELLING TT/OD | BUYINGTT | BUYINGCP | SWIFT CODE

For CNY -> MYR we take BUYINGTT ÷ UNIT (bank buys CNY). The scraper normalizes
header whitespace, so "BUYING TT" / "BUYINGTT" both match.
"""

from __future__ import annotations

from decimal import Decimal

import httpx
import pytest
import respx

from app.scrapers.base import ScraperError
from app.scrapers.sc import StandardCharteredScraper

URL = "https://www.sc.com/my/deposits/interest-rates/"

# (unit, currency, selling_ttod, buying_tt, buying_cp, swift)
Row = tuple[str, str, str, str, str, str]


def _fx_table(rows: list[Row]) -> str:
    head = (
        "<tr><th>UNIT</th><th>CURRENCY</th><th>SELLING TT/OD</th>"
        "<th>BUYING TT</th><th>BUYING CP</th><th>SWIFT CODE</th></tr>"
    )
    body = ""
    for unit, cur, sell, btt, bcp, swift in rows:
        body += (
            f"<tr><td>{unit}</td><td>{cur}</td><td>{sell}</td>"
            f"<td>{btt}</td><td>{bcp}</td><td>{swift}</td></tr>"
        )
    return f"<table>{head}{body}</table>"


def _decoy_deposit_table() -> str:
    return (
        "<table><tr><th>Tenure</th><th>Rate % p.a.</th></tr>"
        "<tr><td>12 months</td><td>2.50</td></tr></table>"
    )


def _page(rows: list[Row]) -> str:
    return (
        "<!DOCTYPE html><html><body>" f"{_decoy_deposit_table()}{_fx_table(rows)}" "</body></html>"
    )


LIVE: list[Row] = [
    ("1", "U.S. DOLLARS", "4.0726", "3.8665", "3.8643", "USD"),
    ("100", "CHINESE RENMINBI", "60.4479", "56.6256", "0", "CNY"),
    ("1", "EURO", "4.8045", "4.448", "4.4167", "EUR"),
]


@pytest.mark.asyncio
@respx.mock
async def test_sc_picks_cny_buying_tt_over_decoy_and_divides_by_unit():
    respx.get(URL).mock(return_value=httpx.Response(200, text=_page(LIVE)))

    r = await StandardCharteredScraper().fetch("CNY", "MYR")

    # 56.6256 / 100 = 0.56625600
    assert r.rate == Decimal("0.56625600")
    assert Decimal("0.5") <= r.rate <= Decimal("0.8")
    assert r.rate_type == "tt_buy"
    assert r.fee_estimate is None
    assert r.raw_payload["buying_tt"] == "56.6256"
    assert r.raw_payload["unit"] == "100"
    assert r.raw_payload["selling_tt_od"] == "60.4479"
    assert r.raw_payload["buying_cp"] == "0"


@pytest.mark.asyncio
@respx.mock
async def test_sc_raises_when_cny_row_missing():
    rows: list[Row] = [("1", "U.S. DOLLARS", "4.0726", "3.8665", "3.8643", "USD")]
    respx.get(URL).mock(return_value=httpx.Response(200, text=_page(rows)))
    with pytest.raises(ScraperError, match="missing marker|no row containing"):
        await StandardCharteredScraper().fetch("CNY", "MYR")


@pytest.mark.asyncio
@respx.mock
async def test_sc_raises_on_zero_buying_tt():
    rows: list[Row] = [("100", "CHINESE RENMINBI", "60.4479", "0", "0", "CNY")]
    respx.get(URL).mock(return_value=httpx.Response(200, text=_page(rows)))
    with pytest.raises(ScraperError, match="unavailable|zero"):
        await StandardCharteredScraper().fetch("CNY", "MYR")


@pytest.mark.asyncio
@respx.mock
async def test_sc_raises_on_out_of_range_rate():
    """Forgetting ÷ UNIT lands at 56.62 — must trip the sanity check."""
    rows: list[Row] = [("1", "CHINESE RENMINBI", "60.4479", "56.6256", "0", "CNY")]
    respx.get(URL).mock(return_value=httpx.Response(200, text=_page(rows)))
    with pytest.raises(ScraperError, match="sanity check failed"):
        await StandardCharteredScraper().fetch("CNY", "MYR")


@pytest.mark.asyncio
@respx.mock
async def test_sc_raises_on_page_marker_missing():
    junk = "<html><body><p>Service unavailable</p></body></html>"
    respx.get(URL).mock(return_value=httpx.Response(200, text=junk))
    with pytest.raises(ScraperError, match="missing marker"):
        await StandardCharteredScraper().fetch("CNY", "MYR")


@pytest.mark.asyncio
@respx.mock
async def test_sc_raises_on_403():
    respx.get(URL).mock(return_value=httpx.Response(403, text="Forbidden"))
    with pytest.raises(ScraperError, match="403"):
        await StandardCharteredScraper().fetch("CNY", "MYR")


@pytest.mark.asyncio
async def test_sc_rejects_non_myr_quote():
    with pytest.raises(ScraperError, match="only MYR"):
        await StandardCharteredScraper().fetch("CNY", "USD")


@pytest.mark.asyncio
async def test_sc_rejects_non_cny_base():
    with pytest.raises(ScraperError, match="only CNY base"):
        await StandardCharteredScraper().fetch("USD", "MYR")
