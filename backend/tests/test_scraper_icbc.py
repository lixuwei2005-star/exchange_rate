"""ICBC (工商银行) scraper tests.

ICBC's rate page is a Vue SPA; rates come from a JSON API:
  POST https://papi.icbc.com.cn/exchanges/ns/getLatest
  -> {"code":0,"data":[{"currencyENName":"MYR","foreignSell":"171.38",...}]}
`foreignSell` is 现汇卖出价 (CNY per 100 MYR). For CNY -> MYR we store
100 / foreignSell (the bank SELLS MYR for CNY — CLAUDE.md §2.4).
"""

from __future__ import annotations

from decimal import Decimal

import httpx
import pytest
import respx

from app.scrapers.base import ScraperError
from app.scrapers.icbc import API_URL, ICBCScraper


def _entry(en: str, ch: str, foreign_sell: str, *, foreign_buy: str = "0.00") -> dict:
    return {
        "currencyType": "032",
        "currencyCHName": ch,
        "currencyENName": en,
        "reference": foreign_sell,
        "foreignBuy": foreign_buy,
        "foreignSell": foreign_sell,
        "cashBuy": foreign_buy,
        "cashSell": foreign_sell,
        "publishDate": "2026-05-29",
        "publishTime": "21:02:59",
    }


def _payload(*entries: dict, code: int = 0) -> dict:
    return {"code": code, "message": "success", "data": list(entries)}


LIVE = _payload(
    _entry("USD", "美元", "676.65"),
    _entry("MYR", "马来西亚林吉特", "171.38"),
    _entry("HKD", "港币", "86.55"),
)


@pytest.mark.asyncio
@respx.mock
async def test_icbc_picks_myr_foreign_sell_and_divides_by_100():
    respx.post(API_URL).mock(return_value=httpx.Response(200, json=LIVE))

    r = await ICBCScraper().fetch("CNY", "MYR")

    # 100 / 171.38
    assert r.rate == (Decimal("100") / Decimal("171.38")).quantize(Decimal("0.00000001"))
    assert Decimal("0.5") <= r.rate <= Decimal("0.8")
    assert r.rate_type == "bank_ask"
    assert r.fee_estimate is None
    assert r.raw_payload["foreign_sell_per_100"] == "171.38"
    assert r.raw_payload["publish_date"] == "2026-05-29"


@pytest.mark.asyncio
@respx.mock
async def test_icbc_raises_on_non_zero_code():
    respx.post(API_URL).mock(return_value=httpx.Response(200, json=_payload(code=1)))
    with pytest.raises(ScraperError, match="code==0|unexpected payload"):
        await ICBCScraper().fetch("CNY", "MYR")


@pytest.mark.asyncio
@respx.mock
async def test_icbc_raises_when_myr_missing():
    respx.post(API_URL).mock(
        return_value=httpx.Response(200, json=_payload(_entry("USD", "美元", "676.65")))
    )
    with pytest.raises(ScraperError, match="no entry for MYR"):
        await ICBCScraper().fetch("CNY", "MYR")


@pytest.mark.asyncio
@respx.mock
async def test_icbc_raises_when_foreign_sell_unavailable():
    respx.post(API_URL).mock(
        return_value=httpx.Response(200, json=_payload(_entry("MYR", "马来西亚林吉特", "--")))
    )
    with pytest.raises(ScraperError, match="unavailable"):
        await ICBCScraper().fetch("CNY", "MYR")


@pytest.mark.asyncio
@respx.mock
async def test_icbc_raises_on_out_of_range_rate():
    # foreignSell 10.0 -> 100/10 = 10, far above the upper bound
    respx.post(API_URL).mock(
        return_value=httpx.Response(200, json=_payload(_entry("MYR", "马来西亚林吉特", "10.00")))
    )
    with pytest.raises(ScraperError, match="sanity check failed"):
        await ICBCScraper().fetch("CNY", "MYR")


@pytest.mark.asyncio
@respx.mock
async def test_icbc_raises_on_http_error():
    respx.post(API_URL).mock(return_value=httpx.Response(500, text="oops"))
    with pytest.raises(ScraperError, match="HTTP error"):
        await ICBCScraper().fetch("CNY", "MYR")


@pytest.mark.asyncio
async def test_icbc_rejects_non_cny_base():
    with pytest.raises(ScraperError, match="only CNY base"):
        await ICBCScraper().fetch("USD", "MYR")
