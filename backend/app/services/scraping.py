"""One-shot scraper execution: invoke the scraper, persist a snapshot row,
update channel status, append a log entry. Used by the scheduler and by the
admin "Scrape now" button."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.db import SessionLocal
from app.models.channel import Channel
from app.models.rate_snapshot import RateSnapshot
from app.models.scrape_log import ScrapeLog
from app.scrapers import ALL_SCRAPERS
from app.scrapers.base import ScraperError

logger = logging.getLogger(__name__)


async def _log(
    session: AsyncSession, *, channel_code: str | None, level: str, message: str
) -> None:
    session.add(
        ScrapeLog(
            channel_code=channel_code,
            level=level,
            message=message[:2000],
            created_at=datetime.now(UTC),
        )
    )


async def run_scraper(
    channel_code: str, base: str = "CNY", quote: str = "MYR"
) -> RateSnapshot | None:
    """Run one scraper. Persist snapshot on success, log error on failure.
    Returns the new snapshot (or None on failure)."""
    scraper_cls = ALL_SCRAPERS.get(channel_code)
    if scraper_cls is None:
        raise ValueError(f"unknown channel: {channel_code}")
    scraper = scraper_cls()

    async with SessionLocal() as session:
        channel = await session.get(Channel, channel_code)
        if channel is None:
            raise ValueError(f"channel '{channel_code}' not in DB; run make seed")
        now = datetime.now(UTC)
        try:
            result = await scraper.fetch(base, quote)
        except (ScraperError, NotImplementedError) as exc:
            channel.last_error_at = now
            channel.last_error_msg = str(exc)[:1000]
            await _log(session, channel_code=channel_code, level="error", message=str(exc))
            await session.commit()
            logger.warning("scraper %s failed: %s", channel_code, exc)
            return None
        except Exception as exc:  # unexpected
            channel.last_error_at = now
            channel.last_error_msg = f"unexpected: {exc!r}"[:1000]
            await _log(
                session, channel_code=channel_code, level="error", message=f"unexpected: {exc!r}"
            )
            await session.commit()
            logger.exception("scraper %s crashed", channel_code)
            return None

        snap = RateSnapshot(
            channel_code=channel_code,
            base_currency=result.base_currency,
            quote_currency=result.quote_currency,
            rate=result.rate,
            rate_type=result.rate_type,
            fee_estimate=result.fee_estimate,
            fee_currency=result.fee_currency,
            raw_payload=result.raw_payload,
            fetched_at=now,
        )
        session.add(snap)
        channel.last_success_at = now
        channel.last_error_msg = None
        await _log(
            session,
            channel_code=channel_code,
            level="info",
            message=f"ok: {result.base_currency}->{result.quote_currency} rate={result.rate}",
        )
        await session.commit()
        await session.refresh(snap)
        logger.info("scraper %s ok: rate=%s", channel_code, result.rate)
        return snap
