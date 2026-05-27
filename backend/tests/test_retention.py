from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.models.rate_snapshot import RateSnapshot
from app.models.scrape_log import ScrapeLog
from app.services.retention import run_retention


@pytest.mark.asyncio
async def test_retention_collapses_old_snapshots_to_daily(session):
    # Seed: 100-days-old day with 5 snapshots, 95-days-old day with 3,
    # 30-days-old day with 4 (within 90-day raw window — should be untouched).
    base_old = datetime.now(UTC) - timedelta(days=100)
    snaps = []
    for h in range(5):
        snaps.append(
            RateSnapshot(
                channel_code="midmarket",
                base_currency="CNY",
                quote_currency="MYR",
                rate=Decimal("0.65"),
                rate_type="midmarket",
                raw_payload={},
                fetched_at=base_old.replace(hour=h),
            )
        )
    base_old2 = datetime.now(UTC) - timedelta(days=95)
    for h in range(3):
        snaps.append(
            RateSnapshot(
                channel_code="midmarket",
                base_currency="CNY",
                quote_currency="MYR",
                rate=Decimal("0.65"),
                rate_type="midmarket",
                raw_payload={},
                fetched_at=base_old2.replace(hour=h),
            )
        )
    recent = datetime.now(UTC) - timedelta(days=30)
    for h in range(4):
        snaps.append(
            RateSnapshot(
                channel_code="midmarket",
                base_currency="CNY",
                quote_currency="MYR",
                rate=Decimal("0.65"),
                rate_type="midmarket",
                raw_payload={},
                fetched_at=recent.replace(hour=h),
            )
        )
    session.add_all(snaps)
    await session.commit()

    result = await run_retention()
    assert result["snapshots_removed"] == 4 + 2  # 5-1 + 3-1

    # After retention: 1 + 1 + 4 = 6 rows total
    count = (await session.execute(select(func.count(RateSnapshot.id)))).scalar_one()
    assert count == 6


@pytest.mark.asyncio
async def test_retention_prunes_old_logs(session):
    old = datetime.now(UTC) - timedelta(days=45)
    fresh = datetime.now(UTC) - timedelta(days=5)
    session.add(ScrapeLog(channel_code=None, level="info", message="old", created_at=old))
    session.add(ScrapeLog(channel_code=None, level="info", message="fresh", created_at=fresh))
    await session.commit()

    result = await run_retention()
    assert result["logs_removed"] == 1
    msgs = (await session.execute(select(ScrapeLog.message))).scalars().all()
    assert list(msgs) == ["fresh"]
