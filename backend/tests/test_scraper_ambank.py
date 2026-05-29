"""AmBank Malaysia scraper tests.

AmBank renders one server-side table (Sitefinity/Kendo). Header row uses plain
<td> cells, first column is a flag image with an empty header:
  (flag) | Currency | Currency Unit | Selling TT / OD (RM) | Buying TT (RM) | Buying OD (RM)
Header and data rows have the SAME column count, so a header-label lookup maps
straight to the data-cell index. For CNY -> MYR we take Buying TT ÷ Currency
Unit (the bank BUYS CNY, gives MYR).
"""

from __future__ import annotations

from decimal import Decimal

import httpx
import pytest
import respx

from app.scrapers.ambank import AmBankScraper
from app.scrapers.base import ScraperError

URL = "https://www.ambank.com.my/rates-fees-charges/foreign-exchange-rates"

# (name, unit, selling_tt_od, buying_tt, buying_od)
Row = tuple[str, str, str, str, str]


def _table(rows: list[Row]) -> str:
    head = (
        "<tr style='background-color: rgba(255,0,0,1)'>"
        "<td>&nbsp;</td><td>Currency</td><td>Currency Unit</td>"
        "<td>Selling TT / OD (RM)</td><td>Buying TT (RM)</td><td>Buying OD (RM)</td>"
        "</tr>"
    )
    body = ""
    for name, unit, sell, buy_tt, buy_od in rows:
        body += (
            "<tr>"
            "<td><img src='/flag.jpg'></td>"
            f"<td>{name}</td><td>{unit}</td><td>{sell}</td><td>{buy_tt}</td><td>{buy_od}</td>"
            "</tr>"
        )
    return f'<table class="table table-bordered k-table"><tbody>{head}{body}</tbody></table>'


def _page(rows: list[Row]) -> str:
    return (
        "<!DOCTYPE html><html><body><main>"
        "<h3>Foreign Exchange Rates</h3><p>Last Update: 29 May 2026</p>"
        f"{_table(rows)}"
        "</main></body></html>"
    )


LIVE: list[Row] = [
    ("Australian Dollar", "1", "2.9219", "2.7590", "2.7590"),
    ("Chinese Renminbi", "100", "61.2100", "56.1200", "56.1200"),
    ("US Dollar", "1", "4.0730", "3.8690", "3.8690"),
]


@pytest.mark.asyncio
@respx.mock
async def test_ambank_picks_cny_buy_tt_and_divides_by_unit():
    respx.get(URL).mock(return_value=httpx.Response(200, text=_page(LIVE)))

    r = await AmBankScraper().fetch("CNY", "MYR")

    # 56.1200 / 100 = 0.56120000
    assert r.rate == Decimal("0.56120000")
    assert Decimal("0.5") <= r.rate <= Decimal("0.8")
    assert r.rate_type == "tt_buy"
    assert r.fee_estimate is None
    assert r.raw_payload["buying_tt"] == "56.1200"
    assert r.raw_payload["currency_unit"] == "100"
    assert r.raw_payload["selling_tt_od"] == "61.2100"
    assert r.raw_payload["buying_od"] == "56.1200"


@pytest.mark.asyncio
@respx.mock
async def test_ambank_raises_when_buy_tt_zero():
    # AmBank shows 0 for many currencies it doesn't actively quote.
    rows: list[Row] = [("Chinese Renminbi", "100", "61.2100", "0", "0.0000")]
    respx.get(URL).mock(return_value=httpx.Response(200, text=_page(rows)))
    with pytest.raises(ScraperError, match="zero|unavailable"):
        await AmBankScraper().fetch("CNY", "MYR")


@pytest.mark.asyncio
@respx.mock
async def test_ambank_raises_when_cny_row_missing():
    rows: list[Row] = [("US Dollar", "1", "4.0730", "3.8690", "3.8690")]
    respx.get(URL).mock(return_value=httpx.Response(200, text=_page(rows)))
    with pytest.raises(ScraperError, match="no <table> containing|no row containing"):
        await AmBankScraper().fetch("CNY", "MYR")


@pytest.mark.asyncio
@respx.mock
async def test_ambank_raises_on_page_marker_missing():
    junk = "<html><body><p>Service temporarily unavailable</p></body></html>"
    respx.get(URL).mock(return_value=httpx.Response(200, text=junk))
    with pytest.raises(ScraperError, match="missing marker"):
        await AmBankScraper().fetch("CNY", "MYR")


@pytest.mark.asyncio
@respx.mock
async def test_ambank_raises_on_403():
    respx.get(URL).mock(return_value=httpx.Response(403, text="Forbidden"))
    with pytest.raises(ScraperError, match="403"):
        await AmBankScraper().fetch("CNY", "MYR")


@pytest.mark.asyncio
@respx.mock
async def test_ambank_raises_on_out_of_range_rate():
    """Forgetting ÷ Currency Unit lands at 56.12 — must trip the sanity check."""
    rows: list[Row] = [("Chinese Renminbi", "1", "61.2100", "56.1200", "56.1200")]
    respx.get(URL).mock(return_value=httpx.Response(200, text=_page(rows)))
    with pytest.raises(ScraperError, match="sanity check failed"):
        await AmBankScraper().fetch("CNY", "MYR")


@pytest.mark.asyncio
async def test_ambank_rejects_non_myr_quote():
    with pytest.raises(ScraperError, match="only MYR"):
        await AmBankScraper().fetch("CNY", "USD")


@pytest.mark.asyncio
async def test_ambank_rejects_non_cny_base():
    with pytest.raises(ScraperError, match="only CNY base"):
        await AmBankScraper().fetch("USD", "MYR")
