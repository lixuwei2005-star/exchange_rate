"""CIMB scraper tests.

CIMB's business forex page renders three tables; each lives inside a
self-contained `<div class="cmp-rates-charges rc-table ...">` wrapper that
also carries the section heading + 'Last Updated' text in plain text.
Columns in the TT tables: Country | Country Code | Selling TT/OD |
Buying TT | Buying OD. CNY sits in the 'Per 100 Units' table — we take
Buying TT and divide by 100."""

from __future__ import annotations

from decimal import Decimal

import httpx
import pytest
import respx

from app.scrapers.base import ScraperError
from app.scrapers.cimb import CIMBScraper

URL = "https://www.cimb.com.my/en/business/help-and-support/rates-charges/forex-rates.html"


def _wrapper(
    section_heading: str, table_html: str, *, last_updated: str = "9:10 am, 28 May 2026, Thursday"
) -> str:
    """A single rates-table section as CIMB renders it: heading + last-
    updated text + a <table>, all inside the rc-table wrapper div."""
    return f"""
<div class="cmp-rates-charges rc-table lock-header table-content">
  {section_heading} Table
  Last Updated: {last_updated}
  <div class="table-5-col table-unit-forex relative">
    <div class="table-scroll-area table-wrapper">
      {table_html}
    </div>
  </div>
</div>
"""


def _tt_table(rows: list[tuple[str, str, str, str, str]]) -> str:
    """A TT table: Country | Country Code | Selling TT/OD | Buying TT | Buying OD."""
    body = """
        <tr>
          <th class="col-header">Country</th>
          <th class="col-header">Country Code</th>
          <th class="col-header">Selling TT/OD</th>
          <th class="col-header">Buying TT</th>
          <th class="col-header">Buying OD</th>
        </tr>
    """
    for country, code, sell, buy_tt, buy_od in rows:
        body += f"""
        <tr>
          <td>{country}</td>
          <td>{code}</td>
          <td>{sell}</td>
          <td>{buy_tt}</td>
          <td>{buy_od}</td>
        </tr>
        """
    return f"<table><tbody>{body}</tbody></table>"


def _full_page(per_unit_rows: list, per_100_rows: list, notes_rows: list | None = None) -> str:
    per_unit = _wrapper("Per Unit of Foreign Currency", _tt_table(per_unit_rows))
    per_100 = _wrapper("Per 100 Units of Foreign Currency", _tt_table(per_100_rows))
    notes = ""
    if notes_rows is not None:
        notes = _wrapper("Currency Notes", _tt_table(notes_rows))
    return f"""<!DOCTYPE html><html><body>
<div class="root responsivegrid">
  <h1>Forex Rates</h1>
  {per_unit}
  {per_100}
  {notes}
</div>
</body></html>"""


# Realistic test fixtures, matching the verified shape of CIMB's live response.
PER_UNIT_ROWS = [
    ("AUSTRALIAN DOLLAR", "AUD", "2.9096", "2.7501", "2.7500"),
    ("EURO", "EUR", "4.7260", "4.5092", "4.5005"),
    ("US DOLLAR", "USD", "4.2750", "4.2050", "4.2030"),
]
PER_100_ROWS_WITH_CNY = [
    ("UTD. ARAB EMIR. DIRHAM", "AED", "114.9950", "100.6726", "100.6187"),
    ("BANGLADESHI TAKA", "BDT", "3.4967", "2.9493", "2.7434"),
    ("CHINESE YUAN", "CNY", "60.4250", "56.7976", "55.9071"),
    ("HONG KONG DOLLAR", "HKD", "51.9858", "49.2844", "48.4584"),
]


@pytest.mark.asyncio
@respx.mock
async def test_cimb_picks_cny_from_per_100_table_and_divides_by_100():
    respx.get(URL).mock(
        return_value=httpx.Response(200, text=_full_page(PER_UNIT_ROWS, PER_100_ROWS_WITH_CNY))
    )

    r = await CIMBScraper().fetch("CNY", "MYR")

    # 56.7976 / 100 = 0.56797600
    assert r.rate == Decimal("0.56797600")
    assert Decimal("0.5") <= r.rate <= Decimal("0.8")
    assert r.rate_type == "tt_buy"
    assert r.fee_estimate is None
    assert r.fee_currency is None
    assert r.raw_payload["country_code"] == "CNY"
    assert r.raw_payload["country_label"] == "CHINESE YUAN"
    assert r.raw_payload["multiplier"] == 100
    assert r.raw_payload["buying_tt"] == "56.7976"
    assert r.raw_payload["section"] == "Per 100 Units of Foreign Currency"
    assert "May 2026" in (r.raw_payload["last_updated"] or "")


@pytest.mark.asyncio
@respx.mock
async def test_cimb_ignores_per_unit_table_even_if_it_contains_a_cny_row():
    """Defense in depth: if some future page version puts a stray CNY row
    in the per-unit table, we should still ONLY look at the per-100 table
    (because that's where the multiplier semantics make sense)."""
    per_unit_with_stray_cny = PER_UNIT_ROWS + [
        ("CHINESE YUAN", "CNY", "0.60", "0.59", "0.58"),  # would be wrong if used
    ]
    respx.get(URL).mock(
        return_value=httpx.Response(
            200, text=_full_page(per_unit_with_stray_cny, PER_100_ROWS_WITH_CNY)
        )
    )

    r = await CIMBScraper().fetch("CNY", "MYR")
    # Confirms we used the per-100 row, not the stray per-unit row.
    assert r.raw_payload["buying_tt"] == "56.7976"
    assert r.rate == Decimal("0.56797600")


@pytest.mark.asyncio
@respx.mock
async def test_cimb_raises_when_cny_row_missing():
    rows_without_cny = [r for r in PER_100_ROWS_WITH_CNY if r[1] != "CNY"]
    respx.get(URL).mock(
        return_value=httpx.Response(200, text=_full_page(PER_UNIT_ROWS, rows_without_cny))
    )
    with pytest.raises(ScraperError, match="no row for country code"):
        await CIMBScraper().fetch("CNY", "MYR")


@pytest.mark.asyncio
@respx.mock
async def test_cimb_raises_when_buying_tt_is_na():
    rows = [
        ("CHINESE YUAN", "CNY", "60.4250", "N/A", "55.9071"),
    ]
    respx.get(URL).mock(return_value=httpx.Response(200, text=_full_page(PER_UNIT_ROWS, rows)))
    with pytest.raises(ScraperError, match="N/A|cannot compute"):
        await CIMBScraper().fetch("CNY", "MYR")


@pytest.mark.asyncio
@respx.mock
async def test_cimb_raises_on_page_marker_missing():
    # Body lacks the per-100 marker → treat as junk/WAF page
    junk = "<html><body><p>Service temporarily unavailable</p></body></html>"
    respx.get(URL).mock(return_value=httpx.Response(200, text=junk))
    with pytest.raises(ScraperError, match="missing the section marker"):
        await CIMBScraper().fetch("CNY", "MYR")


@pytest.mark.asyncio
@respx.mock
async def test_cimb_raises_on_403():
    respx.get(URL).mock(return_value=httpx.Response(403, text="Forbidden"))
    with pytest.raises(ScraperError, match="403"):
        await CIMBScraper().fetch("CNY", "MYR")


@pytest.mark.asyncio
async def test_cimb_rejects_non_myr_quote():
    with pytest.raises(ScraperError, match="only MYR"):
        await CIMBScraper().fetch("CNY", "USD")
