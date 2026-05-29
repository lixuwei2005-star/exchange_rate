"""Hong Leong Bank Malaysia scraper tests.

HLB's forex board renders one table where each cell is self-labelling::

    <td><div class="left-col">Buying (TT)</div><div class="right-col">56.6000</div></td>

so values are located by LABEL, not column position. The CNY row's name cell
carries the per-unit basis ("RINGGIT TO 100 UNITS OF FOREIGN CURRENCY"). For
CNY → MYR we take **Buying (TT)** ÷ multiplier (the bank BUYS CNY, gives MYR).
"""

from __future__ import annotations

from decimal import Decimal

import httpx
import pytest
import respx

from app.scrapers.base import ScraperError
from app.scrapers.hlb import HLBScraper

URL = "https://www.hlb.com.my/en/global-markets/forex-rates.html"


def _cny_row(
    *,
    multiplier: str = "100",
    selling: str = "60.4000",
    buy_tt: str = "56.6000",
    buy_od: str = "--",
    pref_selling: str = "--",
    pref_buying: str = "--",
) -> str:
    """Build a CNY <tr> mirroring HLB's real left-col/right-col cell layout."""
    return f"""
    <tr>
      <td class="forex-rates-table-data col-desktop">
        <div class="img-thumbnail flag flag-icon-cn"></div>
      </td>
      <td class="forex-rates-table-data">
        <div class="left-col">RINGGIT TO {multiplier} UNITS OF FOREIGN CURRENCY</div>
        <div class="right-col">
          <div class="img-thumbnail flag flag-icon-cn mobile-data"></div>
          CHINESE RENMINBI (CNY)
        </div>
      </td>
      <td class="forex-rates-table-data text-center">
        <div class="left-col">Selling (TT/OD/TC)</div>
        <div class="right-col">{selling}</div>
      </td>
      <td class="forex-rates-table-data text-center">
        <div class="left-col">Buying (TT)</div>
        <div class="right-col">{buy_tt}</div>
      </td>
      <td class="forex-rates-table-data text-center">
        <div class="left-col">Buying (OD/TC)</div>
        <div class="right-col">{buy_od}</div>
      </td>
      <td class="forex-rates-table-data text-center col">
        <div>FOREIGN CURRENCY ACCOUNT PREFERENTIAL FOREX RATE</div>
      </td>
      <td class="forex-rates-table-data text-center">
        <div class="left-col">Selling</div>
        <div class="right-col">{pref_selling}</div>
      </td>
      <td class="forex-rates-table-data text-center">
        <div class="left-col">Buying</div>
        <div class="right-col">{pref_buying}</div>
      </td>
    </tr>"""


_USD_ROW = """
    <tr>
      <td class="forex-rates-table-data col-desktop"><div class="flag flag-icon-us"></div></td>
      <td class="forex-rates-table-data">
        <div class="left-col">RINGGIT TO 1 UNIT OF FOREIGN CURRENCY</div>
        <div class="right-col">US DOLLAR (USD)</div>
      </td>
      <td class="forex-rates-table-data text-center">
        <div class="left-col">Selling (TT/OD/TC)</div><div class="right-col">4.2800</div>
      </td>
      <td class="forex-rates-table-data text-center">
        <div class="left-col">Buying (TT)</div><div class="right-col">4.2300</div>
      </td>
      <td class="forex-rates-table-data text-center">
        <div class="left-col">Buying (OD/TC)</div><div class="right-col">4.2100</div>
      </td>
    </tr>"""


def _page(*rows: str) -> str:
    return (
        "<!DOCTYPE html><html><body>"
        "<h1>Forex Rates</h1>"
        f"<table>{''.join(rows)}</table>"
        "</body></html>"
    )


@pytest.mark.asyncio
@respx.mock
async def test_hlb_picks_cny_buy_tt_and_divides_by_multiplier():
    respx.get(URL).mock(return_value=httpx.Response(200, text=_page(_USD_ROW, _cny_row())))

    r = await HLBScraper().fetch("CNY", "MYR")

    # 56.6000 / 100 = 0.56600000
    assert r.rate == Decimal("0.56600000")
    assert Decimal("0.5") <= r.rate <= Decimal("0.8")
    assert r.rate_type == "tt_buy"
    assert r.fee_estimate is None
    assert r.fee_currency is None
    assert r.raw_payload["buying_tt"] == "56.6000"
    assert r.raw_payload["selling"] == "60.4000"
    assert r.raw_payload["multiplier"] == "100"


@pytest.mark.asyncio
@respx.mock
async def test_hlb_ignores_preferential_and_od_buying():
    """The row carries three 'Buying'-ish cells: Buying (TT), Buying (OD/TC),
    and a preferential-account 'Buying'. We must take only Buying (TT)."""
    row = _cny_row(buy_tt="56.6000", buy_od="55.0000", pref_buying="99.9999")
    respx.get(URL).mock(return_value=httpx.Response(200, text=_page(row)))

    r = await HLBScraper().fetch("CNY", "MYR")

    assert r.rate == Decimal("0.56600000")
    assert r.raw_payload["buying_tt"] == "56.6000"
    assert r.raw_payload["buying_od_tc"] == "55.0000"


@pytest.mark.asyncio
@respx.mock
async def test_hlb_raises_when_buy_tt_unavailable():
    respx.get(URL).mock(return_value=httpx.Response(200, text=_page(_cny_row(buy_tt="--"))))
    with pytest.raises(ScraperError, match="unavailable|cannot"):
        await HLBScraper().fetch("CNY", "MYR")


@pytest.mark.asyncio
@respx.mock
async def test_hlb_raises_when_cny_row_missing():
    respx.get(URL).mock(return_value=httpx.Response(200, text=_page(_USD_ROW)))
    with pytest.raises(ScraperError, match="no row containing"):
        await HLBScraper().fetch("CNY", "MYR")


@pytest.mark.asyncio
@respx.mock
async def test_hlb_raises_on_page_marker_missing():
    junk = "<html><body><p>Service temporarily unavailable</p></body></html>"
    respx.get(URL).mock(return_value=httpx.Response(200, text=junk))
    with pytest.raises(ScraperError, match="missing marker"):
        await HLBScraper().fetch("CNY", "MYR")


@pytest.mark.asyncio
@respx.mock
async def test_hlb_raises_on_403():
    respx.get(URL).mock(return_value=httpx.Response(403, text="Forbidden"))
    with pytest.raises(ScraperError, match="403"):
        await HLBScraper().fetch("CNY", "MYR")


@pytest.mark.asyncio
@respx.mock
async def test_hlb_raises_on_out_of_range_rate():
    """Forgetting ÷ multiplier lands at 56.6, far above the upper bound — must
    trip the sanity check rather than silently storing nonsense."""
    respx.get(URL).mock(return_value=httpx.Response(200, text=_page(_cny_row(multiplier="1"))))
    with pytest.raises(ScraperError, match="sanity check failed"):
        await HLBScraper().fetch("CNY", "MYR")


@pytest.mark.asyncio
async def test_hlb_rejects_non_myr_quote():
    with pytest.raises(ScraperError, match="only MYR"):
        await HLBScraper().fetch("CNY", "USD")


@pytest.mark.asyncio
async def test_hlb_rejects_non_cny_base():
    with pytest.raises(ScraperError, match="only CNY base"):
        await HLBScraper().fetch("USD", "MYR")
