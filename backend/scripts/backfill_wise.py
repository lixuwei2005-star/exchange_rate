"""Backfill Wise's recent intraday rate history into rate_snapshots.

Wise's marketing site exposes an unauthenticated hourly history series:

    GET https://wise.com/rates/history+live
        ?source=CNY&target=MYR&length=<N>&resolution=hourly&unit=day
    -> [{"source":"CNY","target":"MYR","value":0.5844,"time":<epoch_ms>}, ...]

`value` is target-per-source = MYR per 1 CNY, which is exactly our storage
convention, so we store it directly as a Wise snapshot. This seeds the
intraday (24h/72h) chart immediately; going forward the 10-minute scraper
keeps adding finer-grained points.

Idempotent: a Wise snapshot already at a given timestamp is left alone, so
re-running is safe and won't duplicate hourly points.

Run (on the server):
    docker compose exec backend python scripts/backfill_wise.py            # 4 days hourly
    docker compose exec backend python scripts/backfill_wise.py --days 7
    docker compose exec backend python scripts/backfill_wise.py --dry-run
or:  make backfill-wise
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime
from decimal import Decimal

import httpx

URL = "https://wise.com/rates/history+live"
BASE = "CNY"
QUOTE = "MYR"
CHANNEL = "wise"
# The marketing endpoint serves browsers; use a browser UA so it doesn't 403.
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


async def _fetch_series(days: int) -> list[tuple[datetime, Decimal]]:
    params = {
        "source": BASE,
        "target": QUOTE,
        "length": str(days),
        "resolution": "hourly",
        "unit": "day",
    }
    async with httpx.AsyncClient(timeout=25, headers={"User-Agent": UA}) as client:
        resp = await client.get(URL, params=params)
        resp.raise_for_status()
        payload = resp.json()
    if not isinstance(payload, list):
        raise SystemExit(f"unexpected response shape: {type(payload).__name__}")
    out: list[tuple[datetime, Decimal]] = []
    for p in payload:
        if not isinstance(p, dict) or p.get("value") is None or p.get("time") is None:
            continue
        ts = datetime.fromtimestamp(int(p["time"]) / 1000, tz=UTC)
        rate = Decimal(str(p["value"])).quantize(Decimal("0.00000001"))
        if rate > 0:
            out.append((ts, rate))
    out.sort(key=lambda x: x[0])
    return out


async def backfill(days: int, dry_run: bool) -> None:
    series = await _fetch_series(days)
    if series:
        first, last = series[0][0], series[-1][0]
        print(f"fetched {len(series)} hourly point(s): {first.isoformat()} → {last.isoformat()}")
        print(f"  latest: 1 MYR = {1 / series[-1][1]:.4f} CNY")
    else:
        print("fetched 0 points")
    if dry_run:
        print("dry-run: no DB writes")
        return

    from sqlalchemy import select

    from app.db import SessionLocal
    from app.models.rate_snapshot import RateSnapshot

    async with SessionLocal() as session:
        existing = {
            (ts if ts.tzinfo else ts.replace(tzinfo=UTC))
            for ts in (
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
        }
        inserted = 0
        for ts, rate in series:
            if ts in existing:
                continue
            session.add(
                RateSnapshot(
                    channel_code=CHANNEL,
                    base_currency=BASE,
                    quote_currency=QUOTE,
                    rate=rate,
                    rate_type="p2p",
                    # headline extraction for wise reads raw_payload["rate"];
                    # store the mid-market value there so the chart shows it.
                    raw_payload={"rate": float(rate), "backfilled": True},
                    fetched_at=ts,
                )
            )
            inserted += 1
        await session.commit()
    print(f"inserted {inserted} new snapshot(s); skipped {len(series) - inserted} already present")


def main() -> None:
    ap = argparse.ArgumentParser(description="Backfill Wise hourly rate history.")
    ap.add_argument(
        "--days", type=int, default=4, help="days of hourly history to fetch (default 4)"
    )
    ap.add_argument("--dry-run", action="store_true", help="fetch + parse only, no DB writes")
    args = ap.parse_args()
    asyncio.run(backfill(args.days, args.dry_run))


if __name__ == "__main__":
    main()
