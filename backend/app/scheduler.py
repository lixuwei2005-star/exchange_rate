from __future__ import annotations

import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select

from app.db import SessionLocal
from app.models.channel import Channel

# Importing registers all scraper classes.
from app.scrapers import ALL_SCRAPERS  # noqa: F401
from app.services.retention import run_retention
from app.services.scraping import run_scraper
from app.services.settings import get_setting
from app.services.summary import regenerate as regenerate_summary

logger = logging.getLogger(__name__)

# Server is in Singapore (OCI Singapore region). ai.schedule_cron in §10 is SGT.
scheduler = AsyncIOScheduler(timezone="Asia/Singapore")

# Per-channel refresh intervals (minutes). Source: CLAUDE.md §6. These are
# polite poll intervals — actual data freshness is bounded by how often the
# upstream source itself publishes:
#   - Frankfurter (midmarket): daily, around CET 16:00 (~SGT 22:00)
#   - Wise: intraday, changes throughout the day
#   - BOC: a few times per business day (Beijing time)
#   - UnionPay / Visa / MC: intraday-ish
#   - Maybank / CIMB: typically twice per business day (Malaysia time)
# Polling more often than the source updates is harmless (we just write the
# same snapshot) but doesn't actually make displayed numbers fresher.
REFRESH_MINUTES: dict[str, int] = {
    # Frankfurter publishes ECB rates once a day around CET 16:00; polling
    # hourly is plenty (worst-case lag = 1 hour after ECB publishes).
    "midmarket": 60,
    "wise": 10,
    "boc": 15,
    "visa": 30,
    "mastercard": 30,
    "maybank": 180,
    "cimb": 180,
    # NOTE: unionpay is NOT here on purpose — it gets a daily cron (see
    # CHANNEL_CRONS below) because its source is a once-per-day static
    # file named by Beijing date.
}

# Channels that prefer a daily cron over an IntervalTrigger because the
# upstream publishes at a known wall-clock time. Each value is a CronTrigger.
CHANNEL_CRONS: dict[str, CronTrigger] = {
    # UnionPay locks MYR rate at 11:00 Beijing time; we fetch at 11:30 to
    # give a comfortable margin. Asia/Shanghai and Asia/Singapore share the
    # same UTC offset, but be explicit about the wall clock the source uses.
    "unionpay": CronTrigger(hour=11, minute=30, timezone="Asia/Shanghai"),
}


def schedule_channel(code: str) -> None:
    """Add (or replace) a scheduled job for one channel. Used at startup and
    by the admin "toggle active" endpoint. Picks a cron trigger for channels
    listed in CHANNEL_CRONS, an IntervalTrigger otherwise."""

    async def _job() -> None:
        await run_scraper(code, base="CNY", quote="MYR")

    trigger: CronTrigger | IntervalTrigger
    if code in CHANNEL_CRONS:
        trigger = CHANNEL_CRONS[code]
    else:
        minutes = REFRESH_MINUTES.get(code, 60)
        trigger = IntervalTrigger(minutes=minutes, jitter=30)

    scheduler.add_job(
        _job,
        trigger=trigger,
        id=f"scrape:{code}",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        name=f"scrape {code}",
    )


def unschedule_channel(code: str) -> None:
    job_id = f"scrape:{code}"
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)


async def _seed_active_jobs() -> None:
    async with SessionLocal() as session:
        rows = await session.execute(select(Channel).where(Channel.active.is_(True)))
        active_codes = [ch.code for ch in rows.scalars() if ch.code in ALL_SCRAPERS]

        # AI cron (CLAUDE.md §10). Uses the SGT timezone configured on the
        # scheduler. Skipped if `ai.enabled` is false or cron is empty.
        if (await get_setting(session, "ai.enabled", "false")).lower() == "true":
            cron = (await get_setting(session, "ai.schedule_cron", "")).strip()
            if cron:
                try:
                    scheduler.add_job(
                        _ai_summary_job,
                        trigger=CronTrigger.from_crontab(cron, timezone="Asia/Singapore"),
                        id="ai:summary",
                        replace_existing=True,
                        coalesce=True,
                    )
                    logger.info("scheduled ai:summary on cron %r SGT", cron)
                except Exception as exc:
                    logger.warning("ai.schedule_cron %r is invalid: %s", cron, exc)

    for code in active_codes:
        schedule_channel(code)
        # Also fire once immediately so a backend restart doesn't leave the
        # homepage showing pre-restart data for up to `interval` minutes
        # while the IntervalTrigger waits for its first scheduled fire.
        asyncio.create_task(run_scraper(code, base="CNY", quote="MYR"))


async def _ai_summary_job() -> None:
    await regenerate_summary("CNY", "MYR")


async def _retention_job() -> None:
    await run_retention()


def start() -> None:
    if scheduler.running:
        return
    scheduler.start()
    # Defer the DB lookup so it runs inside the asyncio loop after startup.
    asyncio.create_task(_seed_active_jobs())
    # Nightly retention at 04:00 SGT (off-peak).
    scheduler.add_job(
        _retention_job,
        trigger=CronTrigger(hour=4, minute=0, timezone="Asia/Singapore"),
        id="retention:nightly",
        replace_existing=True,
        coalesce=True,
    )
    logger.info("APScheduler started (timezone=Asia/Singapore, retention=04:00 SGT)")


def shutdown() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
