"""HSBC Malaysia scraper tests.

The currency-rate page server-renders several tables. The TT tables' header is:

    Currency | Currency Name | TT Sell | TT Buy

with the multiplier in the table caption ("... to N Units of Foreign
Currency"). The currency code sits in the row's <th>. CNY lives in the
per-100 table. For CNY -> MYR we take TT Buy ÷ caption-multiplier (100).
The Notes (cash) table has no 'TT Buy' header and must be skipped; the
per-1 TT table has no CNY row and must be skipped.
"""

from __future__ import annotations

from decimal import Decimal

import httpx
import pytest
import respx

from app.scrapers.base import ScraperError
from app.scrapers.hsbc import HSBCScraper

URL = "https://www.hsbc.com.my/investments/products/foreign-exchange/currency-rate/"


def _tt_table(caption: str, rows: list[tuple[str, str, str, str]]) -> str:
    """rows = [(code, name, tt_sell, tt_buy)]."""
    head = "<tr><th>Currency</th><th>Currency Name</th>" "<th>TT Sell</th><th>TT Buy</th></tr>"
    body = ""
    for code, name, sell, buy in rows:
        body += (
            f"<tr><th scope='row'>{code}</th><td>{name}</td>" f"<td>{sell}</td><td>{buy}</td></tr>"
        )
    return f"<table><caption>{caption}</caption>{head}{body}</table>"


def _notes_table() -> str:
    # Cash/Notes table: different headers, no 'TT Buy' — must be ignored.
    return (
        "<table><caption>Bank Notes</caption>"
        "<tr><th>Currency</th><th>Currency Name</th><th>We Sell</th><th>We Buy</th></tr>"
        "<tr><th scope='row'>CNY</th><td>Chinese Renminbi</td><td>62.0000</td><td>55.0000</td></tr>"
        "</table>"
    )


CAP100 = "Exchange Rates in Units of Local Currency to 100 Units of Foreign Currency"
CAP1 = "Exchange Rates in Units of Local Currency to 1 Unit of Foreign Currency"


def _page(per100_rows: list[tuple[str, str, str, str]]) -> str:
    # A per-1 TT table (USD/EUR, no CNY), the per-100 TT table (with CNY),
    # and a Notes table — in document order, to mirror the real page.
    per1 = _tt_table(CAP1, [("USD", "US Dollar", "4.30", "4.20"), ("EUR", "Euro", "4.90", "4.80")])
    per100 = _tt_table(CAP100, per100_rows)
    return f"<!DOCTYPE html><html><body>{per1}{per100}{_notes_table()}</body></html>"


LIVE_100 = [
    ("CHF", "Swiss Franc", "517.8100", "494.8200"),
    ("CNY", "Chinese Renminbi", "59.7600", "57.4100"),
    ("DKK", "Danish Kroner", "64.3600", "59.4100"),
]


@pytest.mark.asyncio
@respx.mock
async def test_hsbc_picks_cny_tt_buy_from_per100_table():
    respx.get(URL).mock(return_value=httpx.Response(200, text=_page(LIVE_100)))

    r = await HSBCScraper().fetch("CNY", "MYR")

    # TT Buy 57.4100 / 100 = 0.57410000 (NOT the Notes 55.00).
    assert r.rate == Decimal("0.57410000")
    assert Decimal("0.5") <= r.rate <= Decimal("0.8")
    assert r.rate_type == "tt_buy"
    assert r.fee_estimate is None
    assert r.raw_payload["tt_buy"] == "57.4100"
    assert r.raw_payload["multiplier"] == 100
    assert r.raw_payload["tt_sell"] == "59.7600"
    assert "100 Units" in r.raw_payload["caption"]


@pytest.mark.asyncio
@respx.mock
async def test_hsbc_raises_when_cny_row_missing():
    rows = [("CHF", "Swiss Franc", "517.8100", "494.8200")]
    respx.get(URL).mock(return_value=httpx.Response(200, text=_page(rows)))
    with pytest.raises(ScraperError, match="no TT <table>|with a 'CNY'"):
        await HSBCScraper().fetch("CNY", "MYR")


@pytest.mark.asyncio
@respx.mock
async def test_hsbc_raises_when_caption_has_no_multiplier():
    bad = _tt_table("Exchange Rates", LIVE_100)  # caption lacks "N Units of Foreign Currency"
    html = f"<!DOCTYPE html><html><body>{bad}</body></html>"
    respx.get(URL).mock(return_value=httpx.Response(200, text=html))
    with pytest.raises(ScraperError, match="multiplier"):
        await HSBCScraper().fetch("CNY", "MYR")


@pytest.mark.asyncio
@respx.mock
async def test_hsbc_raises_on_out_of_range_when_multiplier_is_one():
    """If CNY ever sat in a per-1 table, 57.41 would trip the sanity check."""
    html = f"<!DOCTYPE html><html><body>{_tt_table(CAP1, LIVE_100)}</body></html>"
    respx.get(URL).mock(return_value=httpx.Response(200, text=html))
    with pytest.raises(ScraperError, match="sanity check failed"):
        await HSBCScraper().fetch("CNY", "MYR")


@pytest.mark.asyncio
@respx.mock
async def test_hsbc_raises_on_page_marker_missing():
    junk = "<html><body><p>maintenance</p></body></html>"
    respx.get(URL).mock(return_value=httpx.Response(200, text=junk))
    with pytest.raises(ScraperError, match="missing marker"):
        await HSBCScraper().fetch("CNY", "MYR")


@pytest.mark.asyncio
@respx.mock
async def test_hsbc_raises_on_403():
    respx.get(URL).mock(return_value=httpx.Response(403, text="Forbidden"))
    with pytest.raises(ScraperError, match="403"):
        await HSBCScraper().fetch("CNY", "MYR")


@pytest.mark.asyncio
async def test_hsbc_rejects_non_myr_quote():
    with pytest.raises(ScraperError, match="only MYR"):
        await HSBCScraper().fetch("CNY", "USD")


@pytest.mark.asyncio
async def test_hsbc_rejects_non_cny_base():
    with pytest.raises(ScraperError, match="only CNY base"):
        await HSBCScraper().fetch("USD", "MYR")
