from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models.channel import Channel
from app.models.rate_snapshot import RateSnapshot
from app.schemas.public import HealthResponse, LatestRate

router = APIRouter(prefix="/api", tags=["public"])

# A snapshot is considered "stale" if older than this. Chosen as 1.5x the
# slowest configured refresh (6h → 9h, rounded up to 12h). Tightens in Phase 9.
STALE_THRESHOLD = timedelta(hours=12)


def _as_utc(dt: datetime) -> datetime:
    """SQLite drops tz info — treat naive datetimes from the DB as UTC."""
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


@router.get("/health", response_model=HealthResponse)
async def health(session: Annotated[AsyncSession, Depends(get_session)]) -> HealthResponse:
    """Liveness + freshness summary. Map only includes ACTIVE channels with
    values 'fresh' or 'stale'. Inactive channels are omitted entirely."""
    result = await session.execute(select(Channel).where(Channel.active.is_(True)))
    now = datetime.now(UTC)
    channels: dict[str, str] = {}
    for ch in result.scalars():
        if ch.last_success_at is None:
            channels[ch.code] = "stale"
        elif now - _as_utc(ch.last_success_at) > STALE_THRESHOLD:
            channels[ch.code] = "stale"
        else:
            channels[ch.code] = "fresh"
    return HealthResponse(ok=True, channels=channels)


@router.get("/rates/latest", response_model=list[LatestRate])
async def rates_latest(
    session: Annotated[AsyncSession, Depends(get_session)],
    base: str = Query("CNY"),
    quote: str = Query("MYR"),
) -> list[LatestRate]:
    # subquery: latest fetched_at per active channel for this pair
    latest_subq = (
        select(
            RateSnapshot.channel_code.label("ch"),
            func.max(RateSnapshot.fetched_at).label("m"),
        )
        .where(
            and_(
                RateSnapshot.base_currency == base,
                RateSnapshot.quote_currency == quote,
            )
        )
        .group_by(RateSnapshot.channel_code)
        .subquery()
    )

    q = (
        select(RateSnapshot, Channel)
        .join(
            latest_subq,
            and_(
                latest_subq.c.ch == RateSnapshot.channel_code,
                latest_subq.c.m == RateSnapshot.fetched_at,
            ),
        )
        .join(Channel, Channel.code == RateSnapshot.channel_code)
        .where(
            and_(
                Channel.active.is_(True),
                RateSnapshot.base_currency == base,
                RateSnapshot.quote_currency == quote,
            )
        )
    )
    rows = (await session.execute(q)).all()
    now = datetime.now(UTC)
    out: list[LatestRate] = []
    for snap, channel in rows:
        fetched_at = _as_utc(snap.fetched_at)
        out.append(
            LatestRate(
                channel_code=channel.code,
                channel_name_zh=channel.name_zh,
                rate=snap.rate,
                rate_type=snap.rate_type,
                fee_estimate=snap.fee_estimate,
                fee_currency=snap.fee_currency,
                fetched_at=fetched_at,
                is_stale=(now - fetched_at) > STALE_THRESHOLD,
            )
        )
    out.sort(key=lambda r: r.channel_code)
    return out


@router.get("/rates/history")
async def rates_history(
    base: str = Query("CNY"),
    quote: str = Query("MYR"),
    channel: str = Query(...),
    days: int = Query(30, ge=1, le=365),
):
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="not implemented yet"
    )


@router.get("/summary")
async def summary(
    base: str = Query("CNY"),
    quote: str = Query("MYR"),
):
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="not implemented yet"
    )
