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

# Fallback staleness window for an interval channel with no/odd interval.
STALE_THRESHOLD = timedelta(hours=12)
# Extra margin added on top of a channel's nominal cadence before we call it
# stale, so one missed/late fire (or a cross-midnight gap on a daily/weekly
# channel) doesn't flip a healthy channel to "暂时不可用".
_DAILY_GRACE = timedelta(hours=6)
_WEEKDAY_INDEX = {d: i for i, d in enumerate(("mon", "tue", "wed", "thu", "fri", "sat", "sun"))}


def _stale_threshold_for(ch: Channel) -> timedelta:
    """Derive the staleness window from the channel's SCHEDULE, not a hardcoded
    per-code table. This means any channel the admin switches to daily/weekly
    automatically gets a window wide enough to survive the gap between fires —
    fixing the bug where a 'daily' channel went stale for ~12 h every day under
    the old flat 12 h threshold.

    - interval : 2× the interval, floored at 12 h (covers a missed tick).
    - daily    : 24 h + 6 h grace = 30 h.
    - weekly   : the largest gap between consecutive selected weekdays, + a day,
                 + 6 h grace (so Fri→Mon, a 3-day gap, stays fresh over a
                 weekend). Falls back to 8 days if weekdays are unset/garbled.
    """
    kind = ch.schedule_kind
    if kind == "daily":
        return timedelta(hours=24) + _DAILY_GRACE
    if kind == "weekly":
        days = [d.strip().lower() for d in (ch.weekdays or "").split(",") if d.strip()]
        idx = sorted(_WEEKDAY_INDEX[d] for d in days if d in _WEEKDAY_INDEX)
        if not idx:
            return timedelta(days=8)
        # Largest gap between consecutive runs, wrapping around the week.
        max_gap = max(
            [(b - a) for a, b in zip(idx, idx[1:], strict=False)] + [idx[0] + 7 - idx[-1]]
        )
        return timedelta(days=max_gap) + _DAILY_GRACE
    # interval (default)
    minutes = ch.interval_minutes or 0
    if minutes > 0:
        return max(timedelta(minutes=2 * minutes), STALE_THRESHOLD)
    return STALE_THRESHOLD


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
        elif now - _as_utc(ch.last_success_at) > _stale_threshold_for(ch):
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
        changed_at = await _rate_changed_at(session, channel.code, base, quote, snap)
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
                rate_changed_at=changed_at,
                is_stale=(now - fetched_at) > _stale_threshold_for(channel),
            )
        )
    out.sort(key=lambda r: r.channel_code)
    return out


# How far back to look when finding when the rate last changed. A daily
# channel publishing the same value for a fortnight is unusual; 200 rows
# (e.g. ~33 h for the 10-min Wise poll, or ~25 days for a 3 h bank poll) is a
# generous, cheap bound. If the value never changed within the window we just
# report the oldest seen — honest and never newer than the truth.
_CHANGE_LOOKBACK = 200


async def _rate_changed_at(
    session: AsyncSession,
    channel_code: str,
    base: str,
    quote: str,
    latest: RateSnapshot,
) -> datetime:
    """Return when this channel's rate VALUE last changed: the fetched_at of
    the oldest snapshot in the unbroken run of snapshots (newest-first) whose
    rate equals the latest. So a rate that hasn't moved keeps its original
    'updated' time instead of appearing to refresh on every poll."""
    q = (
        select(RateSnapshot.rate, RateSnapshot.fetched_at)
        .where(
            and_(
                RateSnapshot.channel_code == channel_code,
                RateSnapshot.base_currency == base,
                RateSnapshot.quote_currency == quote,
            )
        )
        .order_by(RateSnapshot.fetched_at.desc())
        .limit(_CHANGE_LOOKBACK)
    )
    changed_at = _as_utc(latest.fetched_at)
    for rate, fetched_at in (await session.execute(q)).all():
        if rate != latest.rate:
            break
        changed_at = _as_utc(fetched_at)
    return changed_at


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
