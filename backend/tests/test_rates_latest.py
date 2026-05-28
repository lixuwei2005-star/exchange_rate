from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest
from httpx import ASGITransport

from app.main import app
from app.models.channel import Channel
from app.models.currency import Currency
from app.models.rate_snapshot import RateSnapshot


@pytest.mark.asyncio
async def test_rates_latest_returns_only_active_channels_latest_snapshot(session):
    # Seed currencies + one active channel + two snapshots (latest wins).
    session.add(Currency(code="CNY", name_en="Chinese Yuan", name_zh="人民币"))
    session.add(Currency(code="MYR", name_en="Malaysian Ringgit", name_zh="马来西亚林吉特"))
    session.add(
        Channel(
            code="midmarket",
            name_en="Mid-market",
            name_zh="中间价（参考）",
            source_url="https://api.frankfurter.app/latest",
            active=True,
        )
    )
    # Inactive channel — should be excluded
    session.add(Channel(code="boc", name_en="BOC", name_zh="中国银行", active=False))

    older = datetime(2026, 5, 27, 10, 0, 0, tzinfo=UTC)
    newer = datetime(2026, 5, 27, 12, 0, 0, tzinfo=UTC)
    session.add_all(
        [
            RateSnapshot(
                channel_code="midmarket",
                base_currency="CNY",
                quote_currency="MYR",
                rate=Decimal("0.65"),
                rate_type="midmarket",
                raw_payload={"x": 1},
                fetched_at=older,
            ),
            RateSnapshot(
                channel_code="midmarket",
                base_currency="CNY",
                quote_currency="MYR",
                rate=Decimal("0.66"),
                rate_type="midmarket",
                raw_payload={"x": 2},
                fetched_at=newer,
            ),
            # Snapshot for inactive channel — should be excluded
            RateSnapshot(
                channel_code="boc",
                base_currency="CNY",
                quote_currency="MYR",
                rate=Decimal("0.64"),
                rate_type="bank_ask",
                raw_payload={},
                fetched_at=newer,
            ),
        ]
    )
    await session.commit()

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/rates/latest", params={"base": "CNY", "quote": "MYR"})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    row = body[0]
    assert row["channel_code"] == "midmarket"
    assert row["channel_name_zh"] == "中间价（参考）"
    assert Decimal(row["rate"]) == Decimal("0.66")  # latest, not older
    # For non-Wise channels, headline_rate == rate.
    assert Decimal(row["headline_rate"]) == Decimal("0.66")
    assert row["rate_type"] == "midmarket"
    assert isinstance(row["is_stale"], bool)


@pytest.mark.asyncio
async def test_rates_latest_empty_when_no_snapshots(session):
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/rates/latest")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_rates_latest_wise_headline_extracted_from_raw_payload(session):
    """For Wise, /api/rates/latest's headline_rate should be the mid-market
    rate baked into the original Wise quote (raw_payload.rate), NOT the
    after-fee effective rate we store in `rate`."""
    session.add(Currency(code="CNY", name_en="Chinese Yuan", name_zh="人民币"))
    session.add(Currency(code="MYR", name_en="Malaysian Ringgit", name_zh="马来西亚林吉特"))
    session.add(Channel(code="wise", name_en="Wise", name_zh="Wise", active=True))
    session.add(
        RateSnapshot(
            channel_code="wise",
            base_currency="CNY",
            quote_currency="MYR",
            rate=Decimal("0.57152"),  # effective, after fee
            rate_type="p2p",
            raw_payload={"rate": 0.58463, "paymentOptions": []},  # mid-market headline
            fetched_at=datetime(2026, 5, 28, 4, 0, tzinfo=UTC),
        )
    )
    await session.commit()

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/rates/latest")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert Decimal(body[0]["rate"]) == Decimal("0.57152")
    assert Decimal(body[0]["headline_rate"]) == Decimal("0.58463")
