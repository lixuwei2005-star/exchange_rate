from __future__ import annotations

from decimal import Decimal

import httpx
import pytest
import respx

from app.scrapers.base import ScraperError
from app.scrapers.maybank import MaybankScraper

URL = "https://www.maybank2u.com.my/maybank2u/malaysia/en/personal/rates/forex_rates.page"


def _page(rows_html: str, *, last_update: str = "May 28, 2026 05:20 PM") -> str:
    """Wraps a small table containing the verified Maybank row shape:
    leading empty <td>, td.currency with a <span>'N FOO'</span>, then
    [TT Selling, TT Buying, OD Buying, Notes Selling, Notes Buying], then
    trailing empty <td>. The PAGE_MARKER 'Chinese Renminbi' must appear
    somewhere in the page body (we include it in the helper fixture row)."""
    return f"""<!DOCTYPE html><html><body>
<div>Forex Rates &mdash; Last Update: {last_update}</div>
<table>
  <thead><tr><th></th><th></th><th>TT Selling</th><th>TT Buying</th><th>OD Buying</th><th>Notes Selling</th><th>Notes Buying</th><th></th></tr></thead>
  <tbody>
    {rows_html}
  </tbody>
</table>
</body></html>"""


def _row(label: str, cols: list[str]) -> str:
    cells = "".join(f"<td>{c}</td>" if c.upper() != "N/A" else "<td><p>N/A</p></td>" for c in cols)
    return f"""
<tr>
  <td></td>
  <td class="currency">
    <div class="group-image-text">
      <img src="/maybank_gif/s_images/flags/flag.gif">
      <span>{label}</span>
    </div>
  </td>
  {cells}
  <td></td>
</tr>
"""


CNY_ROW = _row(
    "100 Chinese Renminbi",
    ["59.9500", "57.4200", "57.4200", "N/A", "N/A"],
)
USD_ROW = _row(
    "1 US Dollar",
    ["4.6800", "4.6500", "4.6500", "4.7000", "4.6300"],
)


@pytest.mark.asyncio
@respx.mock
async def test_maybank_extracts_tt_buying_and_divides_by_multiplier():
    """100 Chinese Renminbi row, TT Buying = 57.4200, multiplier = 100
    → stored rate = 57.4200 / 100 = 0.57420000 MYR per CNY."""
    respx.get(URL).mock(return_value=httpx.Response(200, text=_page(CNY_ROW + USD_ROW)))

    r = await MaybankScraper().fetch("CNY", "MYR")

    assert r.rate == Decimal("0.57420000")
    assert Decimal("0.5") <= r.rate <= Decimal("0.8")
    assert r.rate_type == "tt_buy"
    assert r.fee_estimate is None
    assert r.fee_currency is None
    assert r.raw_payload["currency_label"] == "100 Chinese Renminbi"
    assert r.raw_payload["multiplier"] == 100
    assert r.raw_payload["tt_buying"] == "57.4200"
    assert r.raw_payload["last_update"] == "May 28, 2026 05:20 PM"


@pytest.mark.asyncio
@respx.mock
async def test_maybank_handles_multiplier_one_correctly():
    """For currencies quoted per 1 unit (e.g., USD), multiplier = 1 means
    no division — stored rate equals the TT Buying number as-is."""
    # We only care that the parser DOESN'T divide a 1-multiplier rate. Use
    # a CNY row whose value is in [0.5, 0.8] so the sanity check passes,
    # plus a USD row to exercise the 1-multiplier parsing path indirectly.
    # Targeted test: confirm that the multiplier extraction logic returns 1
    # for "1 US Dollar". We do that by also checking the raw_payload format.
    respx.get(URL).mock(
        return_value=httpx.Response(
            200,
            text=_page(
                _row("1 Chinese Renminbi", ["0.61", "0.5742", "0.5742", "N/A", "N/A"]) + USD_ROW
            ),
        )
    )

    r = await MaybankScraper().fetch("CNY", "MYR")

    # Multiplier 1 → rate equals TT Buying as-is
    assert r.rate == Decimal("0.57420000")
    assert r.raw_payload["multiplier"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_maybank_raises_when_tt_buying_is_na():
    na_row = _row("100 Chinese Renminbi", ["59.95", "N/A", "57.42", "N/A", "N/A"])
    respx.get(URL).mock(return_value=httpx.Response(200, text=_page(na_row)))
    with pytest.raises(ScraperError, match="N/A|cannot compute"):
        await MaybankScraper().fetch("CNY", "MYR")


@pytest.mark.asyncio
@respx.mock
async def test_maybank_raises_when_cny_row_missing():
    # USD row only; the page marker must still appear (in the header copy
    # below) so we hit the 'row not found' branch rather than the marker one.
    body = _page(USD_ROW).replace("Last Update", "Last Update for Chinese Renminbi and others")
    respx.get(URL).mock(return_value=httpx.Response(200, text=body))
    with pytest.raises(ScraperError, match="no row matching"):
        await MaybankScraper().fetch("CNY", "MYR")


@pytest.mark.asyncio
@respx.mock
async def test_maybank_detects_akamai_challenge_page():
    """Response body lacks the rate-table marker (e.g., Akamai interstitial)
    → raise rather than parse junk."""
    challenge_html = (
        "<html><head><title>Pardon Our Interruption</title></head>"
        "<body><p>Access denied. Please complete the challenge.</p></body></html>"
    )
    respx.get(URL).mock(return_value=httpx.Response(200, text=challenge_html))
    with pytest.raises(ScraperError, match="marker|challenge|Akamai"):
        await MaybankScraper().fetch("CNY", "MYR")


@pytest.mark.asyncio
@respx.mock
async def test_maybank_raises_on_403():
    respx.get(URL).mock(return_value=httpx.Response(403, text="Forbidden"))
    with pytest.raises(ScraperError, match="403|Akamai"):
        await MaybankScraper().fetch("CNY", "MYR")


@pytest.mark.asyncio
@respx.mock
async def test_maybank_rejects_non_myr_quote():
    with pytest.raises(ScraperError, match="only MYR"):
        await MaybankScraper().fetch("CNY", "USD")
