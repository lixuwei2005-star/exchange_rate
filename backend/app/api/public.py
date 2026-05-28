from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models.ai_summary import AISummary
from app.models.channel import Channel
from app.models.rate_snapshot import RateSnapshot
from app.schemas.public import (
    HealthResponse,
    HistoryPoint,
    LatestRate,
    SummaryResponse,
    WiseQuoteResponse,
)
from app.scrapers.base import ScraperError
from app.scrapers.wise import WiseScraper

router = APIRouter(prefix="/api", tags=["public"])

# A snapshot is considered "stale" if older than this. Chosen as 1.5x the
# slowest configured refresh (6h → 9h, rounded up to 12h). Tightens in Phase 9.
STALE_THRESHOLD = timedelta(hours=12)


def _as_utc(dt: datetime) -> datetime:
    """SQLite drops tz info — treat naive datetimes from the DB as UTC."""
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _headline_rate_for(snap: RateSnapshot) -> Decimal:
    """Pre-fee advertised rate for the pure-rate comparison table.

    For most channels the stored rate IS the headline (bank's quoted ask,
    card network rate after issuer markup, etc.). Wise is the exception:
    we store the after-fee effective rate, but Wise's actual advertised
    rate is the mid-market value embedded in the quote response's top
    level — extract it from raw_payload so the comparison is honest.
    """
    if snap.channel_code != "wise":
        return snap.rate
    raw = snap.raw_payload if isinstance(snap.raw_payload, dict) else {}
    direct = raw.get("rate")
    if direct is not None:
        try:
            return Decimal(str(direct))
        except Exception:
            pass
    # reverse_pair fallback shape: raw_payload = {"reverse_payload": {"rate": ...}}
    rev = raw.get("reverse_payload")
    if isinstance(rev, dict) and rev.get("rate") is not None:
        try:
            return (Decimal("1") / Decimal(str(rev["rate"]))).quantize(Decimal("0.00000001"))
        except Exception:
            pass
    return snap.rate


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
                is_stale=(now - fetched_at) > STALE_THRESHOLD,
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


@router.get("/quote/wise", response_model=WiseQuoteResponse)
async def quote_wise(
    amount: float = Query(..., gt=0, le=1_000_000),
    base: str = Query("CNY"),
    quote: str = Query("MYR"),
) -> WiseQuoteResponse:
    """On-demand Wise quote for an arbitrary source amount. Used by the
    homepage so the '手续费' column updates as the user types — Wise's fee
    has a large fixed component (≈19 CNY for CNY→MYR) so a single 1000-CNY
    reference snapshot misrepresents the fee at other amounts."""
    try:
        result = await WiseScraper().quote_for_amount(base, quote, amount)
    except ScraperError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return WiseQuoteResponse(
        source_amount=result["source_amount"],  # type: ignore[arg-type]
        target_amount=result["target_amount"],  # type: ignore[arg-type]
        rate=result["rate"],  # type: ignore[arg-type]
        fee=result["fee"],  # type: ignore[arg-type]
        fee_currency=str(result["fee_currency"]),
    )


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
