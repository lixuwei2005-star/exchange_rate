"""Public Bank Malaysia scraper tests.

Public Bank's /en/rates-charges/forex/ renders a single table whose rows
embed the multiplier in the label itself ('100 Chinese Renminbi (Non
Trade)' → ÷100). Columns: Currency | Selling TT/OD | Buying TT |
Buying OD | Currency Notes Selling | Currency Notes Buying. We take
**Buying TT** for CNY → MYR direction (the bank BUYS CNY, gives MYR).
"""

from __future__ import annotations

from decimal import Decimal

import httpx
import pytest
import respx

from app.scrapers.base import ScraperError
from app.scrapers.publicbank import PublicBankScraper

URL = "https://www.pbebank.com/en/rates-charges/forex/"


def _table(rows: list[tuple[str, str, str, str, str, str]]) -> str:
    """Build a Public-Bank-style forex table.

    Each row: (label, selling_tt_od, buying_tt, buying_od, notes_sell, notes_buy).
    """
    body = (
        "<tr>"
        "<th>Currency</th>"
        "<th>Selling TT/OD</th>"
        "<th>Buying TT</th>"
        "<th>Buying OD</th>"
        "<th>Currency Notes Selling</th>"
        "<th>Currency Notes Buying</th>"
        "</tr>"
    )
    for label, sell, buy_tt, buy_od, n_sell, n_buy in rows:
        body += (
            f"<tr>"
            f"<td>{label}</td>"
            f"<td>{sell}</td>"
            f"<td>{buy_tt}</td>"
            f"<td>{buy_od}</td>"
            f"<td>{n_sell}</td>"
            f"<td>{n_buy}</td>"
            f"</tr>"
        )
    return f"<table>{body}</table>"


def _page(rows: list[tuple[str, str, str, str, str, str]]) -> str:
    return f"""<!DOCTYPE html><html><body>
<h1>Foreign Exchange Rates (FOREX)</h1>
<p>Foreign Exchange Rate as at 28 May 2026 08:00 PM</p>
{_table(rows)}
</body></html>"""


# Realistic fixtures matching the verified shape of PB's live response.
LIVE_ROWS: list[tuple[str, str, str, str, str, str]] = [
    ("1 Australian Dollar", "2.8910", "2.7610", "2.7540", "2.9410", "2.6910"),
    ("100 Brunei Dollar", "316.3800", "304.7700", "303.7200", "344.4000", "303.9000"),
    ("100 Chinese Renminbi (Non Trade)", "59.6100", "57.3970", "N/A", "N/A", "N/A"),
    ("1 Euro", "4.7010", "4.5210", "4.5140", "N/A", "N/A"),
]


@pytest.mark.asyncio
@respx.mock
async def test_publicbank_picks_cny_row_and_divides_by_label_multiplier():
    respx.get(URL).mock(return_value=httpx.Response(200, text=_page(LIVE_ROWS)))

    r = await PublicBankScraper().fetch("CNY", "MYR")

    # 57.3970 / 100 = 0.57397000
    assert r.rate == Decimal("0.57397000")
    assert Decimal("0.5") <= r.rate <= Decimal("0.8")
    assert r.rate_type == "tt_buy"
    assert r.fee_estimate is None
    assert r.fee_currency is None
    assert r.raw_payload["row_label"] == "100 Chinese Renminbi (Non Trade)"
    assert r.raw_payload["multiplier"] == 100
    assert r.raw_payload["buying_tt"] == "57.3970"
    assert "28 May 2026" in (r.raw_payload["last_updated"] or "")


@pytest.mark.asyncio
@respx.mock
async def test_publicbank_locates_buying_tt_via_header_not_index():
    """If PB ever swaps columns around, the scraper should still pick the
    Buying TT cell by header text. Simulate a column reordering."""
    swapped_table = (
        "<table>"
        "<tr>"
        "<th>Currency</th>"
        "<th>Buying TT</th>"  # moved to col 1
        "<th>Selling TT/OD</th>"
        "<th>Buying OD</th>"
        "<th>Currency Notes Selling</th>"
        "<th>Currency Notes Buying</th>"
        "</tr>"
        "<tr>"
        "<td>100 Chinese Renminbi (Non Trade)</td>"
        "<td>57.3970</td>"  # now first rate cell
        "<td>59.6100</td>"
        "<td>N/A</td>"
        "<td>N/A</td>"
        "<td>N/A</td>"
        "</tr>"
        "</table>"
    )
    page = (
        "<!DOCTYPE html><html><body>"
        "<h1>Foreign Exchange Rates (FOREX)</h1>"
        "<p>Foreign Exchange Rate as at 28 May 2026 08:00 PM</p>"
        f"{swapped_table}"
        "</body></html>"
    )
    respx.get(URL).mock(return_value=httpx.Response(200, text=page))

    r = await PublicBankScraper().fetch("CNY", "MYR")

    assert r.raw_payload["buying_tt"] == "57.3970"
    assert r.rate == Decimal("0.57397000")


@pytest.mark.asyncio
@respx.mock
async def test_publicbank_currency_notes_selling_header_is_not_misread_as_currency():
    """The header row contains both 'Currency' and 'Currency Notes Selling'.
    The scraper must match 'Currency' as a standalone cell, not as a prefix
    of 'Currency Notes Selling' — otherwise it might pick the wrong header
    row when the table has multiple thead rows."""
    # Build a table whose first row is a junk row containing only 'Currency
    # Notes Selling' (no 'Buying TT'); the real header is the second row.
    # The scraper should skip the junk row and find the real header.
    junk_row_table = (
        "<table>"
        "<tr><th>Currency Notes Selling</th></tr>"  # junk
        "<tr>"
        "<th>Currency</th>"
        "<th>Selling TT/OD</th>"
        "<th>Buying TT</th>"
        "<th>Buying OD</th>"
        "<th>Currency Notes Selling</th>"
        "<th>Currency Notes Buying</th>"
        "</tr>"
        "<tr>"
        "<td>100 Chinese Renminbi (Non Trade)</td>"
        "<td>59.6100</td>"
        "<td>57.3970</td>"
        "<td>N/A</td>"
        "<td>N/A</td>"
        "<td>N/A</td>"
        "</tr>"
        "</table>"
    )
    page = (
        "<!DOCTYPE html><html><body>"
        "<h1>Foreign Exchange Rates (FOREX)</h1>"
        "<p>Foreign Exchange Rate as at 28 May 2026 08:00 PM</p>"
        f"{junk_row_table}"
        "</body></html>"
    )
    respx.get(URL).mock(return_value=httpx.Response(200, text=page))

    r = await PublicBankScraper().fetch("CNY", "MYR")
    assert r.rate == Decimal("0.57397000")


@pytest.mark.asyncio
@respx.mock
async def test_publicbank_raises_when_buying_tt_is_na():
    rows = [
        ("100 Chinese Renminbi (Non Trade)", "59.6100", "N/A", "N/A", "N/A", "N/A"),
    ]
    respx.get(URL).mock(return_value=httpx.Response(200, text=_page(rows)))

    with pytest.raises(ScraperError, match="N/A|cannot compute"):
        await PublicBankScraper().fetch("CNY", "MYR")


@pytest.mark.asyncio
@respx.mock
async def test_publicbank_raises_when_cny_row_missing():
    rows = [
        ("1 Australian Dollar", "2.8910", "2.7610", "2.7540", "2.9410", "2.6910"),
        ("1 Euro", "4.7010", "4.5210", "4.5140", "N/A", "N/A"),
    ]
    respx.get(URL).mock(return_value=httpx.Response(200, text=_page(rows)))

    with pytest.raises(ScraperError, match="no <table> containing|no row matching"):
        await PublicBankScraper().fetch("CNY", "MYR")


@pytest.mark.asyncio
@respx.mock
async def test_publicbank_raises_on_page_marker_missing():
    junk = "<html><body><p>Service temporarily unavailable</p></body></html>"
    respx.get(URL).mock(return_value=httpx.Response(200, text=junk))

    with pytest.raises(ScraperError, match="missing marker"):
        await PublicBankScraper().fetch("CNY", "MYR")


@pytest.mark.asyncio
@respx.mock
async def test_publicbank_raises_on_403():
    respx.get(URL).mock(return_value=httpx.Response(403, text="Forbidden"))

    with pytest.raises(ScraperError, match="403"):
        await PublicBankScraper().fetch("CNY", "MYR")


@pytest.mark.asyncio
async def test_publicbank_rejects_non_myr_quote():
    with pytest.raises(ScraperError, match="only MYR"):
        await PublicBankScraper().fetch("CNY", "USD")


@pytest.mark.asyncio
async def test_publicbank_rejects_non_cny_base():
    with pytest.raises(ScraperError, match="only CNY base"):
        await PublicBankScraper().fetch("USD", "MYR")


@pytest.mark.asyncio
@respx.mock
async def test_publicbank_rejects_out_of_range_rate():
    """If the parser ever miscomputes (e.g. forgets to divide by 100),
    the sanity check in Scraper._sanity_check should bail."""
    # Pretend Buying TT is 5.7397 with multiplier=1 in the label →
    # rate = 5.7397 / 1 = 5.7397, way outside [0.5, 0.8].
    rows = [
        ("1 Chinese Renminbi (Non Trade)", "5.96", "5.7397", "N/A", "N/A", "N/A"),
    ]
    respx.get(URL).mock(return_value=httpx.Response(200, text=_page(rows)))

    with pytest.raises(ScraperError, match="sanity check failed"):
        await PublicBankScraper().fetch("CNY", "MYR")
