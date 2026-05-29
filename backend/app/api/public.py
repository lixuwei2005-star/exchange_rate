from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models.ai_summary import AISummary
from app.models.channel import Channel
from app.models.rate_snapshot import RateSnapshot
from app.schemas.public import (
    ConfigResponse,
    HealthResponse,
    HistoryPoint,
    IntradayPoint,
    LatestRate,
    SummaryResponse,
)
from app.services.rates import as_utc as _as_utc
from app.services.rates import headline_rate_for as _headline_rate_for
from app.services.settings import get_setting

router = APIRouter(prefix="/api", tags=["public"])

# Which channel feeds the homepage hero ("1 MYR = X CNY"). Admin overrides it
# via the `display.headline_channel` setting; this is the install default.
HEADLINE_CHANNEL_KEY = "display.headline_channel"
DEFAULT_HEADLINE_CHANNEL = "midmarket"

# A snapshot is considered "stale" if its last_success is older than this.
# Default tracks the slowest intraday channel; daily channels need a longer
# window so a single missed wall-clock fire doesn't flip them to 'stale'.
STALE_THRESHOLD = timedelta(hours=12)
PER_CHANNEL_STALE_THRESHOLD: dict[str, timedelta] = {
    # UnionPay publishes once per day around 11:00 Beijing time and our
    # cron fires at 11:30; 30 h covers the full day-to-day window plus
    # margin for upstream delays.
    "unionpay": timedelta(hours=30),
}


def _stale_threshold_for(channel_code: str) -> timedelta:
    return PER_CHANNEL_STALE_THRESHOLD.get(channel_code, STALE_THRESHOLD)


@router.get("/config", response_model=ConfigResponse)
async def public_config(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ConfigResponse:
    """Public display config. Currently just which channel the homepage hero
    rate is sourced from. No auth — it's non-sensitive presentation state."""
    code = await get_setting(session, HEADLINE_CHANNEL_KEY, DEFAULT_HEADLINE_CHANNEL)
    return ConfigResponse(headline_channel=code or DEFAULT_HEADLINE_CHANNEL)


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
        elif now - _as_utc(ch.last_success_at) > _stale_threshold_for(ch.code):
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
                headline_rate=_headline_rate_for(snap),
                rate_type=snap.rate_type,
                fee_estimate=snap.fee_estimate,
                fee_currency=snap.fee_currency,
                fetched_at=fetched_at,
                is_stale=(now - fetched_at) > _stale_threshold_for(channel.code),
            )
        )
    out.sort(key=lambda r: r.channel_code)
    return out


@router.get("/rates/history", response_model=list[HistoryPoint])
async def rates_history(
    session: Annotated[AsyncSession, Depends(get_session)],
    base: str = Query("CNY"),
    quote: str = Query("MYR"),
    channel: str = Query(...),
    days: int = Query(30, ge=1, le=365),
) -> list[HistoryPoint]:
    """One point per day (latest snapshot of that day) for the given channel/pair."""
    cutoff = datetime.now(UTC) - timedelta(days=days)
    q = (
        select(RateSnapshot)
        .where(
            and_(
                RateSnapshot.channel_code == channel,
                RateSnapshot.base_currency == base,
                RateSnapshot.quote_currency == quote,
                RateSnapshot.fetched_at >= cutoff,
            )
        )
        .order_by(RateSnapshot.fetched_at)
    )
    snaps = list((await session.execute(q)).scalars())
    by_day: dict[str, RateSnapshot] = {}
    for s in snaps:
        day = _as_utc(s.fetched_at).date().isoformat()
        # keeping the last (latest within day) thanks to ascending order
        by_day[day] = s
    return [HistoryPoint(date=d, rate=s.rate) for d, s in sorted(by_day.items())]


@router.get("/rates/intraday", response_model=list[IntradayPoint])
async def rates_intraday(
    session: Annotated[AsyncSession, Depends(get_session)],
    base: str = Query("CNY"),
    quote: str = Query("MYR"),
    channel: str = Query(...),
    hours: int = Query(72, ge=1, le=168),
) -> list[IntradayPoint]:
    """Every raw snapshot in the last `hours` (NOT bucketed per day, unlike
    /rates/history) for fine-grained intraday charts — e.g. Wise, which we
    poll every ~10 min. Returns the channel's headline rate per point so the
    line matches the comparison table (mid-market for Wise)."""
    cutoff = datetime.now(UTC) - timedelta(hours=hours)
    q = (
        select(RateSnapshot)
        .where(
            and_(
                RateSnapshot.channel_code == channel,
                RateSnapshot.base_currency == base,
                RateSnapshot.quote_currency == quote,
                RateSnapshot.fetched_at >= cutoff,
            )
        )
        .order_by(RateSnapshot.fetched_at)
    )
    snaps = list((await session.execute(q)).scalars())
    return [IntradayPoint(time=_as_utc(s.fetched_at), rate=_headline_rate_for(s)) for s in snaps]


@router.get("/summary", response_model=SummaryResponse)
async def summary(
    session: Annotated[AsyncSession, Depends(get_session)],
    base: str = Query("CNY"),
    quote: str = Query("MYR"),
) -> SummaryResponse:
    q = (
        select(AISummary)
        .where(AISummary.base_currency == base, AISummary.quote_currency == quote)
        .order_by(AISummary.generated_at.desc())
        .limit(1)
    )
    row = (await session.execute(q)).scalar_one_or_none()
    if row is None:
        return SummaryResponse(summary_zh=None, generated_at=None, model_used=None)
    return SummaryResponse(
        summary_zh=row.summary_zh,
        generated_at=_as_utc(row.generated_at),
        model_used=row.model_used,
    )


# Keep this so old callers that hit /rates/latest under unforeseen circumstances
# don't blow up. (No-op — already implemented above.)
_ = status, HTTPException
