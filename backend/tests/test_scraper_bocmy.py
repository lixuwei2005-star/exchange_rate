"""Bank of China (Malaysia) scraper tests.

DISTINCT from the `boc` channel (mainland boc.cn). This is the Malaysian
entity quoting MYR directly. One server-rendered table, header:

    UNIT | Currency | We Buy TT | We Sell TT | We Buy Cash | We Sell Cash | Update Time

For CNY -> MYR we take We Buy TT ÷ 100 (bank buys CNY). The page is actually
GB18030 (it lies about utf-8), so the scraper matches on ASCII only — these
tests serve bytes in gb18030 to mirror that.
"""

from __future__ import annotations

from decimal import Decimal

import httpx
import pytest
import respx

from app.scrapers.base import ScraperError
from app.scrapers.bocmy import BOCMalaysiaScraper

URL = "https://www.bankofchina.com/sourcedb/myr/"

# (code, cn_name, buy_tt, sell_tt, buy_cash, sell_cash)
Row = tuple[str, str, str, str, str, str]


def _page(rows: list[Row]) -> str:
    # Mirror the REAL page: header cells are bilingual and <br/>-split, e.g.
    # <td>买入价<br/>We Buy<br/>TT</td>. So "We Buy TT" is NOT a contiguous
    # string in the raw HTML — the scraper must extract+rejoin cell text and
    # substring-match. (Catches the bug where an exact/raw match failed live.)
    head = (
        "<tr>"
        "<td>单位<br/>UNIT</td><td>货币<br/>Currency</td>"
        "<td>买入价<br/>We Buy<br/>TT</td><td>卖出价<br/>We Sell<br/>TT</td>"
        "<td>现钞买入<br/>We Buy<br/>Cash</td><td>现钞卖出<br/>We Sell<br/>Cash</td>"
        "<td>更新时间<br/>Update Time</td>"
        "</tr>"
    )
    body = ""
    for code, name, btt, stt, bc, sc in rows:
        body += (
            f"<tr><td>{code}</td><td>{name}</td><td>{btt}</td><td>{stt}</td>"
            f"<td>{bc}</td><td>{sc}</td><td>2026/05/30 00:00:01</td></tr>"
        )
    html = (
        "<!DOCTYPE html><html><head><meta charset='utf-8'></head><body>"
        "<h3>Foreign Exchange Rate against MYR</h3>"
        f"<table>{head}{body}</table>"
        "</body></html>"
    )
    return html


def _gb18030(rows: list[Row]) -> bytes:
    # Mirror the real page: Chinese names encoded as GB18030, served under a
    # lying utf-8 charset. The scraper must decode gb18030 + match ASCII.
    return _page(rows).encode("gb18030")


# Chinese names included to exercise the encoding path (人民币 = CNY).
LIVE: list[Row] = [
    ("USD", "美元", "3.908", "4.018", "3.878", "4.048"),
    ("CNY", "人民币", "57.61", "59.56", "57.46", "59.76"),
    ("JPY", "日元", "2.4428", "2.5328", "", ""),
]


@pytest.mark.asyncio
@respx.mock
async def test_bocmy_picks_cny_buy_tt_and_divides_by_100():
    respx.get(URL).mock(return_value=httpx.Response(200, content=_gb18030(LIVE)))

    r = await BOCMalaysiaScraper().fetch("CNY", "MYR")

    # 57.61 / 100 = 0.57610000
    assert r.rate == Decimal("0.57610000")
    assert Decimal("0.5") <= r.rate <= Decimal("0.8")
    assert r.rate_type == "tt_buy"
    assert r.fee_estimate is None
    assert r.raw_payload["we_buy_tt"] == "57.61"
    assert r.raw_payload["multiplier"] == 100
    assert r.raw_payload["we_sell_tt"] == "59.56"


@pytest.mark.asyncio
@respx.mock
async def test_bocmy_raises_when_cny_row_missing():
    rows: list[Row] = [("USD", "美元", "3.908", "4.018", "3.878", "4.048")]
    respx.get(URL).mock(return_value=httpx.Response(200, content=_gb18030(rows)))
    with pytest.raises(ScraperError, match="no row for currency code"):
        await BOCMalaysiaScraper().fetch("CNY", "MYR")


@pytest.mark.asyncio
@respx.mock
async def test_bocmy_raises_on_zero_buy_tt():
    rows: list[Row] = [("CNY", "人民币", "0", "59.56", "", "")]
    respx.get(URL).mock(return_value=httpx.Response(200, content=_gb18030(rows)))
    with pytest.raises(ScraperError, match="unavailable|zero"):
        await BOCMalaysiaScraper().fetch("CNY", "MYR")


@pytest.mark.asyncio
@respx.mock
async def test_bocmy_raises_on_out_of_range_when_not_divided():
    """If the ÷100 were dropped, 57.61 would trip the sanity check. We can't
    'forget' the constant, but a future per-1 board would — guard stays."""
    rows: list[Row] = [("CNY", "人民币", "5761", "5956", "", "")]  # 5761/100 = 57.61
    respx.get(URL).mock(return_value=httpx.Response(200, content=_gb18030(rows)))
    with pytest.raises(ScraperError, match="sanity check failed"):
        await BOCMalaysiaScraper().fetch("CNY", "MYR")


@pytest.mark.asyncio
@respx.mock
async def test_bocmy_raises_on_page_marker_missing():
    junk = "<html><body><p>maintenance</p></body></html>".encode("gb18030")
    respx.get(URL).mock(return_value=httpx.Response(200, content=junk))
    with pytest.raises(ScraperError, match="missing marker"):
        await BOCMalaysiaScraper().fetch("CNY", "MYR")


@pytest.mark.asyncio
@respx.mock
async def test_bocmy_raises_on_403():
    respx.get(URL).mock(return_value=httpx.Response(403, content=b"Forbidden"))
    with pytest.raises(ScraperError, match="403"):
        await BOCMalaysiaScraper().fetch("CNY", "MYR")


@pytest.mark.asyncio
async def test_bocmy_rejects_non_myr_quote():
    with pytest.raises(ScraperError, match="only MYR"):
        await BOCMalaysiaScraper().fetch("CNY", "USD")


@pytest.mark.asyncio
async def test_bocmy_rejects_non_cny_base():
    with pytest.raises(ScraperError, match="only CNY base"):
        await BOCMalaysiaScraper().fetch("USD", "MYR")
