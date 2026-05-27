from __future__ import annotations

from decimal import Decimal

import httpx
import pytest
import respx

from app.scrapers.boc import BOCScraper

BOC_FIXTURE_HTML = """<!DOCTYPE html><html><body>
<table>
  <tr><th>货币名称</th><th>现汇买入价</th><th>现钞买入价</th><th>现汇卖出价</th>
      <th>现钞卖出价</th><th>中行折算价</th><th>发布时间</th></tr>
  <tr><td>美元</td><td>720.10</td><td>715.20</td><td>723.50</td><td>726.80</td>
      <td>721.30</td><td>2026-05-27 16:00</td></tr>
  <tr><td>马来西亚林吉特</td><td>165.10</td><td>160.50</td><td>168.80</td>
      <td>171.10</td><td>166.95</td><td>2026-05-27 16:00</td></tr>
</table>
</body></html>"""


@pytest.mark.asyncio
@respx.mock
async def test_boc_extracts_ask_for_myr_and_normalizes():
    respx.get("https://www.boc.cn/sourcedb/whpj/").mock(
        return_value=httpx.Response(200, text=BOC_FIXTURE_HTML)
    )
    r = await BOCScraper().fetch("CNY", "MYR")
    # ask = 168.80 CNY per 100 MYR  =>  100/168.80 MYR per 1 CNY
    expected = (Decimal("100") / Decimal("168.80")).quantize(Decimal("0.00000001"))
    assert r.rate == expected
    assert r.rate_type == "bank_ask"
    # Sanity: should land in [0.5, 0.8]
    assert Decimal("0.5") <= r.rate <= Decimal("0.8")
