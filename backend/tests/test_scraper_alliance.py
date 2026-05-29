"""Alliance Bank Malaysia scraper tests.

Alliance's forex kiosk renders one <table id="forexList"> with header:
  Foreign Currency | Country | Per Unit | Selling TT | Selling Cash
  | Buying TT | Buying OD | Buying Cash
Header and data rows have the SAME column count, so a header-label lookup maps
straight to the same data-cell index (no offset, unlike RHB). For CNY → MYR we
take **Buying TT** ÷ Per Unit (the bank BUYS CNY, gives MYR).
"""

from __future__ import annotations

from decimal import Decimal

import httpx
import pytest
import respx

from app.scrapers.alliance import AllianceScraper
from app.scrapers.base import ScraperError

URL = (
    "https://www.allianceonline.com.my/personal/rate_charges/" "foreign_exchange_rate_kiosk_view.do"
)

# (name, code, per_unit, selling_tt, selling_cash, buying_tt, buying_od, buying_cash)
Row = tuple[str, str, str, str, str, str, str, str]


def _table(rows: list[Row]) -> str:
    head = (
        "<thead><tr>"
        "<th>Foreign Currency</th><th>Country</th><th>Per Unit</th>"
        "<th>Selling TT</th><th>Selling Cash</th>"
        "<th>Buying TT</th><th>Buying OD</th><th>Buying Cash</th>"
        "</tr></thead>"
    )
    body = ""
    for name, code, unit, sell_tt, sell_cash, buy_tt, buy_od, buy_cash in rows:
        body += (
            "<tr>"
            f"<td>{code} {name}</td><td>{code}</td><td>{unit}</td>"
            f"<td>{sell_tt}</td><td>{sell_cash}</td>"
            f"<td>{buy_tt}</td><td>{buy_od}</td><td>{buy_cash}</td>"
            "</tr>"
        )
    return f'<table class="table-org results" id="forexList">{head}<tbody>{body}</tbody></table>'


def _page(rows: list[Row]) -> str:
    return f"<!DOCTYPE html><html><body><h2>Forex</h2>{_table(rows)}</body></html>"


LIVE_ROWS: list[Row] = [
    ("US DOLLAR", "USD", "1", "4.2800", "4.3000", "4.2300", "4.2100", "4.1900"),
    ("CHINESE RENMINBI", "CNY", "100", "61.0000", "0.0000", "55.3000", "54.2700", "0.0000"),
    ("DANISH KRONA", "DKK", "100", "65.0100", "0.0000", "60.1200", "0.0000", "0.0000"),
]


@pytest.mark.asyncio
@respx.mock
async def test_alliance_picks_cny_buy_tt_and_divides_by_per_unit():
    respx.get(URL).mock(return_value=httpx.Response(200, text=_page(LIVE_ROWS)))

    r = await AllianceScraper().fetch("CNY", "MYR")

    # 55.3000 / 100 = 0.55300000
    assert r.rate == Decimal("0.55300000")
    assert Decimal("0.5") <= r.rate <= Decimal("0.8")
    assert r.rate_type == "tt_buy"
    assert r.fee_estimate is None
    assert r.fee_currency is None
    assert r.raw_payload["buying_tt"] == "55.3000"
    assert r.raw_payload["per_unit"] == "100"
    assert r.raw_payload["selling_tt"] == "61.0000"
    assert r.raw_payload["buying_od"] == "54.2700"


@pytest.mark.asyncio
@respx.mock
async def test_alliance_locates_buy_tt_by_header_when_columns_reordered():
    """If Alliance moves Buying TT, the header-index lookup should still pick
    the right cell rather than a fixed position."""
    reordered = (
        '<table id="forexList">'
        "<thead><tr>"
        "<th>Foreign Currency</th><th>Buying TT</th><th>Country</th><th>Per Unit</th>"
        "<th>Selling TT</th><th>Buying OD</th>"
        "</tr></thead>"
        "<tbody><tr>"
        "<td>CNY CHINESE RENMINBI</td><td>55.3000</td><td>CNY</td><td>100</td>"
        "<td>61.0000</td><td>54.2700</td>"
        "</tr></tbody></table>"
    )
    page = f"<html><body>{reordered}</body></html>"
    respx.get(URL).mock(return_value=httpx.Response(200, text=page))

    r = await AllianceScraper().fetch("CNY", "MYR")
    assert r.rate == Decimal("0.55300000")
    assert r.raw_payload["buying_tt"] == "55.3000"
    assert r.raw_payload["per_unit"] == "100"


@pytest.mark.asyncio
@respx.mock
async def test_alliance_raises_when_buy_tt_zero():
    rows: list[Row] = [
        ("CHINESE RENMINBI", "CNY", "100", "61.0000", "0.0000", "0.0000", "0.0000", "0.0000"),
    ]
    respx.get(URL).mock(return_value=httpx.Response(200, text=_page(rows)))
    with pytest.raises(ScraperError, match="zero|unavailable"):
        await AllianceScraper().fetch("CNY", "MYR")


@pytest.mark.asyncio
@respx.mock
async def test_alliance_raises_when_cny_row_missing():
    rows: list[Row] = [
        ("US DOLLAR", "USD", "1", "4.2800", "4.3000", "4.2300", "4.2100", "4.1900"),
    ]
    respx.get(URL).mock(return_value=httpx.Response(200, text=_page(rows)))
    with pytest.raises(ScraperError, match="no row containing"):
        await AllianceScraper().fetch("CNY", "MYR")


@pytest.mark.asyncio
@respx.mock
async def test_alliance_raises_on_page_marker_missing():
    junk = "<html><body><p>Service temporarily unavailable</p></body></html>"
    respx.get(URL).mock(return_value=httpx.Response(200, text=junk))
    with pytest.raises(ScraperError, match="missing marker"):
        await AllianceScraper().fetch("CNY", "MYR")


@pytest.mark.asyncio
@respx.mock
async def test_alliance_raises_on_403():
    respx.get(URL).mock(return_value=httpx.Response(403, text="Forbidden"))
    with pytest.raises(ScraperError, match="403"):
        await AllianceScraper().fetch("CNY", "MYR")


@pytest.mark.asyncio
@respx.mock
async def test_alliance_raises_on_out_of_range_rate():
    """Forgetting ÷ Per Unit lands at 55.3, far above the upper bound — must
    trip the sanity check rather than silently storing nonsense."""
    rows: list[Row] = [
        ("CHINESE RENMINBI", "CNY", "1", "61.0000", "0.0000", "55.3000", "54.2700", "0.0000"),
    ]
    respx.get(URL).mock(return_value=httpx.Response(200, text=_page(rows)))
    with pytest.raises(ScraperError, match="sanity check failed"):
        await AllianceScraper().fetch("CNY", "MYR")


@pytest.mark.asyncio
async def test_alliance_rejects_non_myr_quote():
    with pytest.raises(ScraperError, match="only MYR"):
        await AllianceScraper().fetch("CNY", "USD")


@pytest.mark.asyncio
async def test_alliance_rejects_non_cny_base():
    with pytest.raises(ScraperError, match="only CNY base"):
        await AllianceScraper().fetch("USD", "MYR")
