"""Backfill UnionPay International daily history into rate_snapshots.

UnionPay publishes a static per-date JSON
(https://www.unionpayintl.com/upload/jfimg/{YYYYMMDD}.json), so — unlike every
other channel — we don't have to wait for the scheduler to accumulate 30 days
of history. We can fetch the past N Beijing days directly and insert any that
are missing.

Idempotent: a UTC day that already has a UnionPay snapshot is left untouched,
so this is safe to re-run and safe to run alongside the daily scheduler job.

Run (on the server):
    docker compose exec backend python scripts/backfill_unionpay.py            # 30 days
    docker compose exec backend python scripts/backfill_unionpay.py --days 60
    docker compose exec backend python scripts/backfill_unionpay.py --dry-run  # fetch+parse only
or:  make backfill-unionpay
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from app.scrapers._common import make_client
from app.scrapers.unionpay import UnionPayScraper

CN_TZ = ZoneInfo("Asia/Shanghai")
BASE = "CNY"
QUOTE = "MYR"
CHANNEL = "unionpay"


async def _fetch_rate_for_date(client, date_str: str) -> Decimal | None:
    """Stored rate (MYR per 1 CNY) for a YYYYMMDD UnionPay file, or None if
    the file 404s / has no usable MYR↔CNY entry."""
    url = UnionPayScraper.URL_TEMPLATE.format(date=date_str)
    resp = await client.get(url)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    payload = resp.json()
    if not isinstance(payload, dict):
        return None
    entry = UnionPayScraper()._find_entry(payload, trans_cur=QUOTE, base_cur=BASE)
    if entry is None or entry.get("rateData") is None:
        return None
    cny_per_quote = Decimal(str(entry["rateData"]))
    if cny_per_quote <= 0:
        return None
    # Storage convention is MYR per 1 CNY (see UnionPayScraper docstring §2.5).
    return (Decimal("1") / cny_per_quote).quantize(Decimal("0.00000001"))


def _fetched_at_for(d) -> datetime:
    """UnionPay locks the rate at 11:00 Beijing; store the snapshot at 11:30
    Beijing (= 03:30 UTC the same calendar date) so the history endpoint —
    which buckets by UTC date — files it under the right day."""
    return datetime(d.year, d.month, d.day, 3, 30, tzinfo=UTC)


async def backfill(days: int, dry_run: bool) -> None:
    today_cn = datetime.now(CN_TZ).date()
    found: list[tuple[object, Decimal]] = []
    async with make_client(UnionPayScraper.timeout_seconds) as client:
        for delta in range(days):
            d = today_cn - timedelta(days=delta)
            date_str = d.strftime("%Y%m%d")
            try:
                rate = await _fetch_rate_for_date(client, date_str)
            except Exception as exc:  # noqa: BLE001 — report and keep going
                print(f"  {date_str}: ERROR {exc}")
                continue
            if rate is None:
                print(f"  {date_str}: no data (404 / no MYR entry)")
                continue
            found.append((d, rate))
            print(f"  {date_str}: 1 MYR = {1 / rate:.4f} CNY  (stored {rate} MYR/CNY)")

    print(f"\nfetched {len(found)} day(s) with data")
    if dry_run:
        print("dry-run: no DB writes")
        return

    # Import DB lazily so --dry-run works without DB config available.
    from sqlalchemy import select

    from app.db import SessionLocal
    from app.models.rate_snapshot import RateSnapshot

    async with SessionLocal() as session:
        rows = (
            (
                await session.execute(
                    select(RateSnapshot.fetched_at).where(
                        RateSnapshot.channel_code == CHANNEL,
                        RateSnapshot.base_currency == BASE,
                        RateSnapshot.quote_currency == QUOTE,
                    )
                )
            )
            .scalars()
            .all()
        )
        existing_days = {
            (ts if ts.tzinfo else ts.replace(tzinfo=UTC)).astimezone(UTC).date() for ts in rows
        }

        inserted = 0
        for d, rate in found:
            if d in existing_days:
                continue
            session.add(
                RateSnapshot(
                    channel_code=CHANNEL,
                    base_currency=BASE,
                    quote_currency=QUOTE,
                    rate=rate,
                    rate_type="card_network",
                    raw_payload={"backfilled": True, "file_date": d.strftime("%Y%m%d")},
                    fetched_at=_fetched_at_for(d),
                )
            )
            inserted += 1
        await session.commit()
    print(f"inserted {inserted} new snapshot(s); skipped {len(found) - inserted} already present")


def main() -> None:
    ap = argparse.ArgumentParser(description="Backfill UnionPay daily rate history.")
    ap.add_argument("--days", type=int, default=30, help="how many days back to fetch (default 30)")
    ap.add_argument("--dry-run", action="store_true", help="fetch + parse only, no DB writes")
    args = ap.parse_args()
    asyncio.run(backfill(args.days, args.dry_run))


if __name__ == "__main__":
    main()
