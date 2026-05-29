"""/api/rates/intraday — un-bucketed raw snapshots within the last N hours.

Unlike /rates/history (one point per day), the intraday endpoint returns
every snapshot in the window, ordered by time, using the channel's headline
rate (mid-market for Wise). Powers the homepage's 24h/72h Wise chart.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
from httpx import ASGITransport

from app.main import app
from app.models.channel import Channel
from app.models.currency import Currency
from app.models.rate_snapshot import RateSnapshot


def _wise_snap(fetched_at: datetime, midmarket: str, effective: str) -> RateSnapshot:
    return RateSnapshot(
        channel_code="wise",
        base_currency="CNY",
        quote_currency="MYR",
        rate=Decimal(effective),  # after-fee effective rate stored in `rate`
        rate_type="p2p",
        raw_payload={"rate": float(midmarket)},  # mid-market headline
        fetched_at=fetched_at,
    )


@pytest.mark.asyncio
async def test_intraday_returns_raw_points_in_window_with_headline(session):
    session.add(Currency(code="CNY", name_en="Chinese Yuan", name_zh="人民币"))
    session.add(Currency(code="MYR", name_en="Malaysian Ringgit", name_zh="马来西亚林吉特"))
    session.add(Channel(code="wise", name_en="Wise", name_zh="Wise", active=True))

    now = datetime.now(UTC)
    session.add_all(
        [
            _wise_snap(now - timedelta(hours=1), "0.58460", "0.57150"),
            _wise_snap(now - timedelta(hours=2), "0.58470", "0.57160"),
            _wise_snap(now - timedelta(hours=10), "0.58400", "0.57100"),
            # Outside a 72h window — must be excluded.
            _wise_snap(now - timedelta(hours=100), "0.59000", "0.57600"),
        ]
    )
    await session.commit()

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/rates/intraday", params={"channel": "wise", "hours": 72})
    assert resp.status_code == 200
    body = resp.json()

    # 3 of 4 points fall within 72h; the 100h-old one is excluded.
    assert len(body) == 3
    # Ascending by time.
    times = [p["time"] for p in body]
    assert times == sorted(times)
    # Headline rate = mid-market (raw_payload.rate), NOT the stored effective rate.
    assert Decimal(body[-1]["rate"]) == Decimal("0.58460")
    assert all(Decimal(p["rate"]) != Decimal("0.57150") for p in body)


@pytest.mark.asyncio
async def test_intraday_empty_when_no_data(session):
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/rates/intraday", params={"channel": "wise", "hours": 24})
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_intraday_rejects_out_of_range_hours(session):
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        too_big = await client.get("/api/rates/intraday", params={"channel": "wise", "hours": 999})
        zero = await client.get("/api/rates/intraday", params={"channel": "wise", "hours": 0})
    assert too_big.status_code == 422
    assert zero.status_code == 422
