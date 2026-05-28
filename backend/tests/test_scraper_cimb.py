from __future__ import annotations

from decimal import Decimal

import httpx
import pytest
import respx

from app.scrapers.cimb import CIMBScraper

# Simple fixture matching what the current CIMB scraper's heuristic looks for.
# The scraper itself is still the prompt 01 stub-style implementation; this
# test just guards against regressions until CIMB is rewritten in its own task.
HTML_FIXTURE = """<!DOCTYPE html><html><body>
<table>
  <tr><th>Currency</th><th>TT Buying</th><th>TT Selling</th></tr>
  <tr><td>USD UNITED STATES</td><td>4.6500</td><td>4.6900</td></tr>
  <tr><td>CHINA RMB</td><td>0.6450</td><td>0.6680</td></tr>
</table>
</body></html>"""


@pytest.mark.asyncio
@respx.mock
async def test_cimb_extracts_tt_buying_for_cny():
    respx.get(
        "https://www.cimb.com.my/en/personal/help-support/rates/"
        "foreign-exchange-counter-rates.html"
    ).mock(return_value=httpx.Response(200, text=HTML_FIXTURE))
    r = await CIMBScraper().fetch("CNY", "MYR")
    assert r.rate == Decimal("0.64500000")
    assert r.rate_type == "tt_buy"
