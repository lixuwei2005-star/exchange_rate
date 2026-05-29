from __future__ import annotations

import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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

# Last-resort fallback when a channel row has schedule_kind='interval' but
# NULL interval_minutes. The real per-channel cadence lives in the
# `channels` table — see §6 of CLAUDE.md and migration 0002.
# CronTrigger times use Asia/Shanghai (UTC+8) for daily channels because
# the upstream sources publish at Beijing wall-clock times.
DEFAULT_INTERVAL_MINUTES = 60


def _trigger_for(ch: Channel) -> CronTrigger | IntervalTrigger:
    """Pick the APScheduler trigger to use for one channel row."""
    if ch.schedule_kind == "daily" and ch.daily_time_cn:
        try:
            h_str, m_str = ch.daily_time_cn.split(":")
            return CronTrigger(hour=int(h_str), minute=int(m_str), timezone="Asia/Shanghai")
        except (ValueError, AttributeError):
            logger.warning(
                "channel %s has invalid daily_time_cn %r; falling back to interval",
                ch.code,
                ch.daily_time_cn,
            )
    minutes = ch.interval_minutes or DEFAULT_INTERVAL_MINUTES
    return IntervalTrigger(minutes=minutes, jitter=30)


def _add_job(code: str, trigger: CronTrigger | IntervalTrigger) -> None:
    async def _job() -> None:
        await run_scraper(code, base="CNY", quote="MYR")

    scheduler.add_job(
        _job,
        trigger=trigger,
        id=f"scrape:{code}",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        name=f"scrape {code}",
    )


async def schedule_channel(code: str) -> None:
    """Add (or replace) a scheduled job for one channel.

    Reads the channel row to pick its trigger (interval / daily). Used at
    startup, by the admin "toggle active" endpoint, and after any
    `/api/admin/channels/{code}` PATCH that changes scheduling fields.
    """
    async with SessionLocal() as session:
        ch = await session.get(Channel, code)
    if ch is None:
        logger.warning("schedule_channel: unknown channel %s", code)
        return
    _add_job(code, _trigger_for(ch))


def unschedule_channel(code: str) -> None:
    job_id = f"scrape:{code}"
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)


async def _seed_active_jobs() -> None:
    async with SessionLocal() as session:
        rows = await session.execute(select(Channel).where(Channel.active.is_(True)))
        active_channels = [ch for ch in rows.scalars() if ch.code in ALL_SCRAPERS]

        # AI auto-summary cron (CLAUDE.md §10): added only when both the AI
        # master switch (ai.enabled) and the schedule toggle (ai.schedule_enabled)
        # are on, with a valid cron. Uses the scheduler's SGT timezone.
        await _apply_ai_schedule(session)

    for ch in active_channels:
        _add_job(ch.code, _trigger_for(ch))
        # Also fire once immediately so a backend restart doesn't leave the
        # homepage showing pre-restart data for up to `interval` minutes
        # while the trigger waits for its first scheduled fire.
        asyncio.create_task(run_scraper(ch.code, base="CNY", quote="MYR"))


async def _ai_summary_job() -> None:
    await regenerate_summary("CNY", "MYR")


AI_SUMMARY_JOB_ID = "ai:summary"


async def _apply_ai_schedule(session: AsyncSession) -> None:
    """Add or remove the AI auto-summary job to match current settings.

    The job exists only when ai.enabled AND ai.schedule_enabled are both true
    and ai.schedule_cron parses. Otherwise it's removed. The cron is a standard
    5-field crontab in SGT; a weekly schedule uses a day-of-week abbreviation
    (e.g. `30 9 * * mon`) written by the admin UI.
    """
    enabled = (await get_setting(session, "ai.enabled", "false")).lower() == "true"
    sched_on = (await get_setting(session, "ai.schedule_enabled", "false")).lower() == "true"
    cron = (await get_setting(session, "ai.schedule_cron", "")).strip()
    if enabled and sched_on and cron:
        try:
            scheduler.add_job(
                _ai_summary_job,
                trigger=CronTrigger.from_crontab(cron, timezone="Asia/Singapore"),
                id=AI_SUMMARY_JOB_ID,
                replace_existing=True,
                coalesce=True,
            )
            logger.info("scheduled %s on cron %r SGT", AI_SUMMARY_JOB_ID, cron)
            return
        except Exception as exc:
            logger.warning("ai.schedule_cron %r is invalid: %s", cron, exc)
    if scheduler.get_job(AI_SUMMARY_JOB_ID):
        scheduler.remove_job(AI_SUMMARY_JOB_ID)
        logger.info(
            "removed %s (ai.enabled=%s ai.schedule_enabled=%s)",
            AI_SUMMARY_JOB_ID,
            enabled,
            sched_on,
        )


async def reschedule_ai_summary() -> None:
    """Re-evaluate the AI auto-summary schedule from settings. Called by the
    admin settings endpoint after ai.enabled / ai.schedule_enabled /
    ai.schedule_cron change. No-op when the scheduler isn't running."""
    if not scheduler.running:
        return
    async with SessionLocal() as session:
        await _apply_ai_schedule(session)


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
