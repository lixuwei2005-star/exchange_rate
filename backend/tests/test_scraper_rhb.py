"""RHB Bank Malaysia scraper tests.

RHB's treasury forex page renders one table with header:
  Foreign Currency | Unit | Bank Sell TT/OD | Bank Buy TT | Bank Buy OD
Data rows split the currency into CODE + NAME cells, so a data row has
one MORE cell than the header. We take **Bank Buy TT** ÷ Unit for the
CNY → MYR direction (the bank BUYS CNY, gives MYR).
"""

from __future__ import annotations

from decimal import Decimal

import httpx
import pytest
import respx

from app.scrapers.base import ScraperError
from app.scrapers.rhb import RHBScraper

URL = "https://www.rhbgroup.com/treasury-rates/foreign-exchange/index.html"


def _table(rows: list[tuple[str, str, str, str, str, str]]) -> str:
    """Build an RHB-style forex table.

    Each row: (code, name, unit, sell_tt_od, buy_tt, buy_od).
    Header has 5 cells (currency is one column); data rows have 6.
    """
    body = (
        "<tr>"
        "<th>Foreign Currency</th>"
        "<th>Unit</th>"
        "<th>Bank Sell TT/OD</th>"
        "<th>Bank Buy TT</th>"
        "<th>Bank Buy OD</th>"
        "</tr>"
    )
    for code, name, unit, sell, buy_tt, buy_od in rows:
        body += (
            f"<tr><td>{code}</td><td>{name}</td><td>{unit}</td>"
            f"<td>{sell}</td><td>{buy_tt}</td><td>{buy_od}</td></tr>"
        )
    return f"<table>{body}</table>"


def _page(rows: list[tuple[str, str, str, str, str, str]]) -> str:
    return f"""<!DOCTYPE html><html><body>
<h2>Foreign Exchange Rates</h2>
{_table(rows)}
</body></html>"""


LIVE_ROWS: list[tuple[str, str, str, str, str, str]] = [
    ("USD", "US Dollar", "1", "4.1210", "3.7660", "3.7250"),
    ("SGD", "Singapore Dollar", "1", "3.2916", "2.9274", "2.9170"),
    ("CNY", "Chinese Renminbi", "100", "65.0100", "52.3300", "54.6300"),
    ("JPY", "Japanese Yen", "100", "2.6370", "2.3529", "2.3220"),
]


@pytest.mark.asyncio
@respx.mock
async def test_rhb_picks_cny_buy_tt_and_divides_by_unit():
    respx.get(URL).mock(return_value=httpx.Response(200, text=_page(LIVE_ROWS)))

    r = await RHBScraper().fetch("CNY", "MYR")

    # 52.3300 / 100 = 0.52330000
    assert r.rate == Decimal("0.52330000")
    assert Decimal("0.45") <= r.rate <= Decimal("0.8")
    assert r.rate_type == "tt_buy"
    assert r.fee_estimate is None
    assert r.fee_currency is None
    assert r.raw_payload["code"] == "CNY"
    assert r.raw_payload["unit"] == "100"
    assert r.raw_payload["bank_buy_tt"] == "52.3300"
    assert r.raw_payload["bank_sell_tt_od"] == "65.0100"
    assert r.raw_payload["bank_buy_od"] == "54.6300"


@pytest.mark.asyncio
@respx.mock
async def test_rhb_locates_buy_tt_by_header_when_columns_reordered():
    """If RHB moves Bank Buy TT to a different position, header lookup +
    the +1 data offset should still pick the right cell."""
    reordered = (
        "<table>"
        "<tr>"
        "<th>Foreign Currency</th>"
        "<th>Bank Buy TT</th>"  # moved up
        "<th>Unit</th>"
        "<th>Bank Sell TT/OD</th>"
        "<th>Bank Buy OD</th>"
        "</tr>"
        "<tr><td>CNY</td><td>Chinese Renminbi</td>"
        "<td>52.3300</td><td>100</td><td>65.0100</td><td>54.6300</td></tr>"
        "</table>"
    )
    page = f"<!DOCTYPE html><html><body><h2>Foreign Exchange Rates</h2>{reordered}</body></html>"
    respx.get(URL).mock(return_value=httpx.Response(200, text=page))

    r = await RHBScraper().fetch("CNY", "MYR")
    assert r.rate == Decimal("0.52330000")
    assert r.raw_payload["bank_buy_tt"] == "52.3300"
    assert r.raw_payload["unit"] == "100"


@pytest.mark.asyncio
@respx.mock
async def test_rhb_raises_when_buy_tt_is_na():
    rows = [("CNY", "Chinese Renminbi", "100", "65.0100", "N/A", "54.6300")]
    respx.get(URL).mock(return_value=httpx.Response(200, text=_page(rows)))
    with pytest.raises(ScraperError, match="N/A|cannot compute"):
        await RHBScraper().fetch("CNY", "MYR")


@pytest.mark.asyncio
@respx.mock
async def test_rhb_raises_when_cny_row_missing():
    rows = [
        ("USD", "US Dollar", "1", "4.1210", "3.7660", "3.7250"),
        ("JPY", "Japanese Yen", "100", "2.6370", "2.3529", "2.3220"),
    ]
    respx.get(URL).mock(return_value=httpx.Response(200, text=_page(rows)))
    with pytest.raises(ScraperError, match="no <table> containing|no row with currency code"):
        await RHBScraper().fetch("CNY", "MYR")


@pytest.mark.asyncio
@respx.mock
async def test_rhb_raises_on_page_marker_missing():
    junk = "<html><body><p>Service temporarily unavailable</p></body></html>"
    respx.get(URL).mock(return_value=httpx.Response(200, text=junk))
    with pytest.raises(ScraperError, match="missing marker"):
        await RHBScraper().fetch("CNY", "MYR")


@pytest.mark.asyncio
@respx.mock
async def test_rhb_raises_on_403():
    respx.get(URL).mock(return_value=httpx.Response(403, text="Forbidden"))
    with pytest.raises(ScraperError, match="403"):
        await RHBScraper().fetch("CNY", "MYR")


@pytest.mark.asyncio
@respx.mock
async def test_rhb_raises_on_out_of_range_rate():
    """A miscomputed rate (e.g. forgetting ÷ Unit) lands at 52.33, far above
    the upper bound — must trip the (widened) sanity check."""
    rows = [("CNY", "Chinese Renminbi", "1", "65.0100", "52.3300", "54.6300")]
    respx.get(URL).mock(return_value=httpx.Response(200, text=_page(rows)))
    with pytest.raises(ScraperError, match="sanity check failed"):
        await RHBScraper().fetch("CNY", "MYR")


@pytest.mark.asyncio
async def test_rhb_rejects_non_myr_quote():
    with pytest.raises(ScraperError, match="only MYR"):
        await RHBScraper().fetch("CNY", "USD")


@pytest.mark.asyncio
async def test_rhb_rejects_non_cny_base():
    with pytest.raises(ScraperError, match="only CNY base"):
        await RHBScraper().fetch("USD", "MYR")
