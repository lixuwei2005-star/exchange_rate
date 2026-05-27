from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

# Importing registers all scraper classes.
from app.scrapers import ALL_SCRAPERS  # noqa: F401
from app.services.scraping import run_scraper

logger = logging.getLogger(__name__)

# Server is in Singapore (OCI Singapore region). ai.schedule_cron in §10 is SGT.
scheduler = AsyncIOScheduler(timezone="Asia/Singapore")

# Per-channel refresh intervals (minutes). Source: CLAUDE.md §6. New scrapers
# get added here as they're implemented.
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


def _schedule_channel(code: str, minutes: int) -> None:
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


def start() -> None:
    if scheduler.running:
        return
    # Phase 4: only midmarket is implemented end-to-end. Other channels get
    # registered as their scrapers come online in Phase 5.
    _schedule_channel("midmarket", REFRESH_MINUTES["midmarket"])
    scheduler.start()
    logger.info(
        "APScheduler started (timezone=Asia/Singapore, jobs=%d)",
        len(scheduler.get_jobs()),
    )


def shutdown() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
