"""Maybank scraper tests.

These tests exercise the parser directly via the pure `_parse` method,
because the live fetch goes through Playwright (Chromium) and can't be
respx-mocked. The HTTP-error / Akamai-detection paths are covered by
calling `_parse` with crafted HTML bodies that mimic what each scenario
would produce; for the real network paths see `make scrape CHANNEL=maybank`
in dev/prod, plus the fallback-to-httpx unit test below."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch

import httpx
import pytest
import respx

from app.scrapers.base import ScraperError
from app.scrapers.maybank import MaybankScraper, _PlaywrightUnavailable

URL = "https://www.maybank2u.com.my/maybank2u/malaysia/en/personal/rates/forex_rates.page"


def _page(rows_html: str, *, last_update: str = "May 28, 2026 05:20 PM") -> str:
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


CNY_ROW = _row("100 Chinese Renminbi", ["59.9500", "57.4200", "57.4200", "N/A", "N/A"])
USD_ROW = _row("1 US Dollar", ["4.6800", "4.6500", "4.6500", "4.7000", "4.6300"])


# ---- _parse: happy paths and structural errors ------------------------


def test_parse_extracts_tt_buying_and_divides_by_multiplier():
    """100 Chinese Renminbi row, TT Buying = 57.4200, multiplier = 100
    → stored rate = 57.4200 / 100 = 0.57420000 MYR per CNY."""
    html = _page(CNY_ROW + USD_ROW)
    r = MaybankScraper()._parse(html, base="CNY", quote="MYR", label_needle="Chinese Renminbi")
    assert r.rate == Decimal("0.57420000")
    assert Decimal("0.5") <= r.rate <= Decimal("0.8")
    assert r.rate_type == "tt_buy"
    assert r.fee_estimate is None
    assert r.fee_currency is None
    assert r.raw_payload["currency_label"] == "100 Chinese Renminbi"
    assert r.raw_payload["multiplier"] == 100
    assert r.raw_payload["tt_buying"] == "57.4200"
    assert r.raw_payload["last_update"] == "May 28, 2026 05:20 PM"


def test_parse_handles_multiplier_one_correctly():
    """multiplier = 1 → rate equals TT Buying as-is (no division bug)."""
    html = _page(_row("1 Chinese Renminbi", ["0.61", "0.5742", "0.5742", "N/A", "N/A"]) + USD_ROW)
    r = MaybankScraper()._parse(html, base="CNY", quote="MYR", label_needle="Chinese Renminbi")
    assert r.rate == Decimal("0.57420000")
    assert r.raw_payload["multiplier"] == 1


def test_parse_raises_when_tt_buying_is_na():
    html = _page(_row("100 Chinese Renminbi", ["59.95", "N/A", "57.42", "N/A", "N/A"]))
    with pytest.raises(ScraperError, match="N/A|cannot compute"):
        MaybankScraper()._parse(html, base="CNY", quote="MYR", label_needle="Chinese Renminbi")


def test_parse_raises_when_cny_row_missing():
    # The marker must still appear in the body (so we hit the 'no row matching'
    # branch, not the 'marker missing' branch). Use a fixture that mentions the
    # marker in the header copy only.
    body = _page(USD_ROW).replace("Last Update", "Last Update for Chinese Renminbi and others")
    with pytest.raises(ScraperError, match="no row matching"):
        MaybankScraper()._parse(body, base="CNY", quote="MYR", label_needle="Chinese Renminbi")


def test_parse_detects_akamai_challenge_page():
    """Body lacks the rate-table marker → raise rather than parse junk."""
    challenge_html = (
        "<html><head><title>Pardon Our Interruption</title></head>"
        "<body><p>Access denied. Please complete the challenge.</p></body></html>"
    )
    with pytest.raises(ScraperError, match="marker|challenge|Akamai"):
        MaybankScraper()._parse(
            challenge_html, base="CNY", quote="MYR", label_needle="Chinese Renminbi"
        )


# ---- fetch: input validation + Playwright unavailable fallback --------


@pytest.mark.asyncio
async def test_fetch_rejects_non_myr_quote():
    with pytest.raises(ScraperError, match="only MYR"):
        await MaybankScraper().fetch("CNY", "USD")


@pytest.mark.asyncio
@respx.mock
async def test_fetch_falls_back_to_httpx_when_playwright_unavailable_and_then_handles_403():
    """When Playwright can't launch (e.g., Chromium not installed locally),
    the scraper falls back to httpx. From OCI the fallback hits Akamai's
    403 — verify we surface that clearly instead of crashing."""

    # Force the playwright path to raise _PlaywrightUnavailable.
    async def _raise_unavailable(self):
        raise _PlaywrightUnavailable("simulated: chromium not installed")

    respx.get(URL).mock(return_value=httpx.Response(403, text="Forbidden"))
    with patch.object(MaybankScraper, "_fetch_via_playwright", _raise_unavailable):
        with pytest.raises(ScraperError, match="403|Akamai"):
            await MaybankScraper().fetch("CNY", "MYR")


@pytest.mark.asyncio
@respx.mock
async def test_fetch_falls_back_to_httpx_when_playwright_unavailable_and_then_parses_real_html():
    """If the fallback httpx GET happens to succeed (e.g., when running from
    a network where Akamai doesn't block), the parser still works on the
    returned HTML."""

    async def _raise_unavailable(self):
        raise _PlaywrightUnavailable("simulated")

    respx.get(URL).mock(return_value=httpx.Response(200, text=_page(CNY_ROW)))
    with patch.object(MaybankScraper, "_fetch_via_playwright", _raise_unavailable):
        r = await MaybankScraper().fetch("CNY", "MYR")
    assert r.rate == Decimal("0.57420000")
