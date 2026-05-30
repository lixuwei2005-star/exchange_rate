"""OCBC Malaysia scraper tests.

The board lives on the internet-banking PUBLIC host (the www page is an
Incapsula shell). One server-rendered table, header:

    Currency | Unit | Sell TT/OD | Buy TT | Buy OD

Each data row's first cell is "CODE NAME" (e.g. "CNY CHINESE YUAN").
Header and data rows have equal column count, so a header-label lookup maps
straight to the data cell. For CNY -> MYR we take Buy TT ÷ Unit, picking the
CNY (onshore) row, NOT the CNH (offshore) row.
"""

from __future__ import annotations

from decimal import Decimal

import httpx
import pytest
import respx

from app.scrapers.base import ScraperError
from app.scrapers.ocbc import OCBCScraper

URL = "https://internet.ocbc.com.my/ocbc-public/ForeignExchangeTTODPublic/Index"

# (code, name, unit, sell_tt_od, buy_tt, buy_od)
Row = tuple[str, str, str, str, str, str]


def _table(rows: list[Row]) -> str:
    head = (
        "<tr><th>Currency</th><th>Unit</th><th>Sell TT/OD</th>"
        "<th>Buy TT</th><th>Buy OD</th></tr>"
    )
    body = ""
    for code, name, unit, sell, buytt, buyod in rows:
        body += (
            "<tr>"
            f"<td>{code}&nbsp;{name}</td><td>{unit}</td>"
            f"<td>{sell}</td><td>{buytt}</td><td>{buyod}</td>"
            "</tr>"
        )
    return f"<table class='table'><tbody>{head}{body}</tbody></table>"


def _page(rows: list[Row]) -> str:
    return (
        "<!DOCTYPE html><html><body>"
        "<div id='lastUpdatedRates'>Last Updated: 30 May 2026</div>"
        f"{_table(rows)}"
        "</body></html>"
    )


LIVE: list[Row] = [
    ("AUD", "AUSTRALIAN DOLLAR", "1", "2.8890", "2.7830", "2.7750"),
    # CNY (onshore) and CNH (offshore) share the name; values differ here so
    # the test proves we key on the CODE and pick CNY.
    ("CNY", "CHINESE YUAN", "100", "59.6800", "57.5400", "57.4400"),
    ("CNH", "CHINESE YUAN (OFFSHORE)", "100", "59.9900", "57.9900", "57.8800"),
    ("USD", "US DOLLAR", "1", "4.0260", "3.8940", "3.8820"),
]


@pytest.mark.asyncio
@respx.mock
async def test_ocbc_picks_cny_buy_tt_over_cnh_and_divides_by_unit():
    respx.get(URL).mock(return_value=httpx.Response(200, text=_page(LIVE)))

    r = await OCBCScraper().fetch("CNY", "MYR")

    # CNY (onshore) Buy TT 57.5400 / 100 = 0.57540000 — NOT the CNH 57.99.
    assert r.rate == Decimal("0.57540000")
    assert Decimal("0.5") <= r.rate <= Decimal("0.8")
    assert r.rate_type == "tt_buy"
    assert r.fee_estimate is None
    assert r.raw_payload["buy_tt"] == "57.5400"
    assert r.raw_payload["unit"] == "100"
    assert r.raw_payload["sell_tt_od"] == "59.6800"
    assert r.raw_payload["buy_od"] == "57.4400"


@pytest.mark.asyncio
@respx.mock
async def test_ocbc_raises_when_cny_row_missing():
    rows: list[Row] = [("USD", "US DOLLAR", "1", "4.0260", "3.8940", "3.8820")]
    respx.get(URL).mock(return_value=httpx.Response(200, text=_page(rows)))
    with pytest.raises(ScraperError, match="no row for currency code"):
        await OCBCScraper().fetch("CNY", "MYR")


@pytest.mark.asyncio
@respx.mock
async def test_ocbc_raises_on_zero_buy_tt():
    rows: list[Row] = [("CNY", "CHINESE YUAN", "100", "59.6800", "0", "0")]
    respx.get(URL).mock(return_value=httpx.Response(200, text=_page(rows)))
    with pytest.raises(ScraperError, match="zero|unavailable"):
        await OCBCScraper().fetch("CNY", "MYR")


@pytest.mark.asyncio
@respx.mock
async def test_ocbc_raises_on_out_of_range_rate():
    """Forgetting ÷ Unit lands at 57.54 — must trip the sanity check."""
    rows: list[Row] = [("CNY", "CHINESE YUAN", "1", "59.6800", "57.5400", "57.4400")]
    respx.get(URL).mock(return_value=httpx.Response(200, text=_page(rows)))
    with pytest.raises(ScraperError, match="sanity check failed"):
        await OCBCScraper().fetch("CNY", "MYR")


@pytest.mark.asyncio
@respx.mock
async def test_ocbc_raises_on_page_marker_missing():
    junk = "<html><body><p>Service temporarily unavailable</p></body></html>"
    respx.get(URL).mock(return_value=httpx.Response(200, text=junk))
    with pytest.raises(ScraperError, match="missing marker"):
        await OCBCScraper().fetch("CNY", "MYR")


@pytest.mark.asyncio
@respx.mock
async def test_ocbc_raises_on_403():
    respx.get(URL).mock(return_value=httpx.Response(403, text="Forbidden"))
    with pytest.raises(ScraperError, match="403"):
        await OCBCScraper().fetch("CNY", "MYR")


@pytest.mark.asyncio
async def test_ocbc_rejects_non_myr_quote():
    with pytest.raises(ScraperError, match="only MYR"):
        await OCBCScraper().fetch("CNY", "USD")


@pytest.mark.asyncio
async def test_ocbc_rejects_non_cny_base():
    with pytest.raises(ScraperError, match="only CNY base"):
        await OCBCScraper().fetch("USD", "MYR")
