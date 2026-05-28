from __future__ import annotations

import re
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import httpx
import pytest
import respx

from app.scrapers.base import ScraperError
from app.scrapers.unionpay import UnionPayScraper

URL_RE = re.compile(r"https://www\.unionpayintl\.com/upload/jfimg/(\d{8})\.json")


def _today_cn_str() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d")


def _yesterday_cn_str() -> str:
    return (datetime.now(ZoneInfo("Asia/Shanghai")) - timedelta(days=1)).strftime("%Y%m%d")


def _file(entries: list[dict]) -> dict:
    return {"exchangeRateJson": entries}


def _myr_cny(rate_data: float) -> dict:
    return {"transCur": "MYR", "baseCur": "CNY", "rateData": rate_data}


def _other(t: str, b: str, r: float) -> dict:
    return {"transCur": t, "baseCur": b, "rateData": r}


@pytest.mark.asyncio
@respx.mock
async def test_unionpay_happy_path_inverts_myr_cny_to_stored_rate():
    """1 MYR = 1.71 CNY  →  stored rate = 1/1.71 ≈ 0.5848 MYR per CNY."""
    today_url = f"https://www.unionpayintl.com/upload/jfimg/{_today_cn_str()}.json"
    respx.get(today_url).mock(
        return_value=httpx.Response(
            200,
            json=_file(
                [
                    _other("AED", "AUD", 0.38477535),
                    _myr_cny(1.71),
                    _other("USD", "CNY", 7.20),
                ]
            ),
        )
    )

    result = await UnionPayScraper().fetch("CNY", "MYR")

    expected = (Decimal("1") / Decimal("1.71")).quantize(Decimal("0.00000001"))
    assert result.rate == expected
    assert Decimal("0.5") <= result.rate <= Decimal("0.8")
    assert result.rate_type == "card_network"
    assert result.fee_estimate is None
    assert result.fee_currency is None
    assert result.raw_payload["file_date"] == _today_cn_str()
    assert result.raw_payload["entry"] == _myr_cny(1.71)


@pytest.mark.asyncio
@respx.mock
async def test_unionpay_raises_when_inversion_skipped_keeps_value_out_of_range():
    """If the inversion bug ever creeps back in, the raw 1.71 lands well
    outside [0.5, 0.8] and the sanity check should reject. Simulate by
    feeding an already-inverted (mistaken) value of 0.05 — out of range."""
    today_url = f"https://www.unionpayintl.com/upload/jfimg/{_today_cn_str()}.json"
    respx.get(today_url).mock(return_value=httpx.Response(200, json=_file([_myr_cny(20.0)])))
    # 1/20 = 0.05, way below the [0.5, 0.8] window
    with pytest.raises(ScraperError):
        await UnionPayScraper().fetch("CNY", "MYR")


@pytest.mark.asyncio
@respx.mock
async def test_unionpay_raises_when_myr_cny_entry_missing():
    today_url = f"https://www.unionpayintl.com/upload/jfimg/{_today_cn_str()}.json"
    respx.get(today_url).mock(
        return_value=httpx.Response(
            200,
            json=_file(
                [
                    _other("MYR", "AUD", 0.32),  # different baseCur — must NOT match
                    _other("USD", "CNY", 7.20),
                ]
            ),
        )
    )
    with pytest.raises(ScraperError, match="no entry"):
        await UnionPayScraper().fetch("CNY", "MYR")


@pytest.mark.asyncio
@respx.mock
async def test_unionpay_falls_back_to_yesterday_on_404():
    today_url = f"https://www.unionpayintl.com/upload/jfimg/{_today_cn_str()}.json"
    yest_url = f"https://www.unionpayintl.com/upload/jfimg/{_yesterday_cn_str()}.json"
    respx.get(today_url).mock(return_value=httpx.Response(404))
    respx.get(yest_url).mock(return_value=httpx.Response(200, json=_file([_myr_cny(1.72)])))

    result = await UnionPayScraper().fetch("CNY", "MYR")

    expected = (Decimal("1") / Decimal("1.72")).quantize(Decimal("0.00000001"))
    assert result.rate == expected
    assert result.raw_payload["file_date"] == _yesterday_cn_str()


@pytest.mark.asyncio
@respx.mock
async def test_unionpay_raises_when_all_candidate_dates_404():
    # 4 days (today + 3 back) all 404
    respx.get(URL_RE).mock(return_value=httpx.Response(404))
    with pytest.raises(ScraperError, match="all .* candidate dates returned 404"):
        await UnionPayScraper().fetch("CNY", "MYR")


@pytest.mark.asyncio
@respx.mock
async def test_unionpay_rejects_non_cny_base():
    with pytest.raises(ScraperError, match="only CNY base"):
        await UnionPayScraper().fetch("USD", "MYR")
