"""Retention / aggregation job (CLAUDE.md §8).

- rate_snapshots: keep raw rows for 90 days. For rows older than that,
  collapse to one per (channel, base, quote, day) — the latest within the
  day — and delete the rest.
- scrape_logs: delete rows older than 30 days.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, delete, func, select

from app.db import SessionLocal
from app.models.rate_snapshot import RateSnapshot
from app.models.scrape_log import ScrapeLog

logger = logging.getLogger(__name__)

SNAPSHOT_RAW_DAYS = 90
LOG_DAYS = 30


async def run_retention() -> dict[str, int]:
    """Returns counts of rows aggregated/deleted for visibility."""
    now = datetime.now(UTC)
    snap_cutoff = now - timedelta(days=SNAPSHOT_RAW_DAYS)
    log_cutoff = now - timedelta(days=LOG_DAYS)

    snaps_removed = 0
    logs_removed = 0

    async with SessionLocal() as session:
        # --- snapshots: keep latest-per-day for everything before the cutoff
        # Query (channel, base, quote, day, max(fetched_at)) buckets to
        # identify the "keep" row, then delete every older row in that
        # bucket. SQLite-friendly approach: GROUP BY day on the fetched_at
        # date and find the max(fetched_at) per group.
        day_col = func.date(RateSnapshot.fetched_at)
        groups_q = (
            select(
                RateSnapshot.channel_code,
                RateSnapshot.base_currency,
                RateSnapshot.quote_currency,
                day_col.label("d"),
                func.max(RateSnapshot.fetched_at).label("keep"),
            )
            .where(RateSnapshot.fetched_at < snap_cutoff)
            .group_by(
                RateSnapshot.channel_code,
                RateSnapshot.base_currency,
                RateSnapshot.quote_currency,
                day_col,
            )
        )
        rows = (await session.execute(groups_q)).all()
        for ch, base, quote, _day, keep in rows:
            del_q = delete(RateSnapshot).where(
                and_(
                    RateSnapshot.channel_code == ch,
                    RateSnapshot.base_currency == base,
                    RateSnapshot.quote_currency == quote,
                    RateSnapshot.fetched_at < snap_cutoff,
                    func.date(RateSnapshot.fetched_at) == _day,
                    RateSnapshot.fetched_at != keep,
                )
            )
            res = await session.execute(del_q)
            snaps_removed += res.rowcount or 0

        # --- scrape_logs: drop everything older than LOG_DAYS
        res = await session.execute(delete(ScrapeLog).where(ScrapeLog.created_at < log_cutoff))
        logs_removed = res.rowcount or 0

        await session.commit()

    logger.info(
        "retention: %d snapshot rows collapsed, %d log rows pruned", snaps_removed, logs_removed
    )
    return {"snapshots_removed": snaps_removed, "logs_removed": logs_removed}
