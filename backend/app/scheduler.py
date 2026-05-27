from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

# Importing ensures all scraper classes are registered. The actual job
# scheduling is wired up starting in Phase 4.
from app.scrapers import ALL_SCRAPERS  # noqa: F401

logger = logging.getLogger(__name__)

# Server is in Singapore (OCI Singapore region). ai.schedule_cron in §10 is SGT.
scheduler = AsyncIOScheduler(timezone="Asia/Singapore")


def start() -> None:
    if not scheduler.running:
        scheduler.start()
        logger.info(
            "APScheduler started (timezone=Asia/Singapore, jobs=%d)", len(scheduler.get_jobs())
        )


def shutdown() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)


# TODO Phase 4+: add scrape jobs here. Empty rotation for now so a fresh boot
# starts the scheduler without firing anything.
SCRAPE_ROTATION: list[str] = []
