from __future__ import annotations

import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select

from app.db import SessionLocal
from app.models.channel import Channel

# Importing registers all scraper classes.
from app.scrapers import ALL_SCRAPERS  # noqa: F401
from app.services.scraping import run_scraper

logger = logging.getLogger(__name__)

# Server is in Singapore (OCI Singapore region). ai.schedule_cron in §10 is SGT.
scheduler = AsyncIOScheduler(timezone="Asia/Singapore")

# Per-channel refresh intervals (minutes). Source: CLAUDE.md §6.
REFRESH_MINUTES: dict[str, int] = {
    "midmarket": 30,
    "wise": 30,
    "boc": 30,
    "unionpay": 60,
    "visa": 60,
    "mastercard": 60,
    "maybank": 360,
    "cimb": 360,
}


def schedule_channel(code: str) -> None:
    """Add (or replace) a scheduled job for one channel. Used at startup and
    by the admin "toggle active" endpoint."""
    minutes = REFRESH_MINUTES.get(code, 60)

    async def _job() -> None:
        await run_scraper(code, base="CNY", quote="MYR")

    scheduler.add_job(
        _job,
        trigger=IntervalTrigger(minutes=minutes, jitter=30),
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
        for ch in rows.scalars():
            if ch.code in ALL_SCRAPERS:
                schedule_channel(ch.code)


def start() -> None:
    if scheduler.running:
        return
    scheduler.start()
    # Defer the DB lookup so it runs inside the asyncio loop after startup.
    asyncio.create_task(_seed_active_jobs())
    logger.info("APScheduler started (timezone=Asia/Singapore)")


def shutdown() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
