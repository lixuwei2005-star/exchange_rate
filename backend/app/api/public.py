from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models.channel import Channel
from app.schemas.public import HealthResponse

router = APIRouter(prefix="/api", tags=["public"])


@router.get("/health", response_model=HealthResponse)
async def health(session: Annotated[AsyncSession, Depends(get_session)]) -> HealthResponse:
    """Liveness + freshness summary. Map values: 'fresh' (recent success),
    'stale' (last success > threshold or never), 'disabled' (active=False)."""
    result = await session.execute(select(Channel))
    channels: dict[str, str] = {}
    for ch in result.scalars():
        if not ch.active:
            channels[ch.code] = "disabled"
        elif ch.last_success_at is None:
            channels[ch.code] = "stale"
        else:
            channels[ch.code] = "fresh"
    return HealthResponse(ok=True, channels=channels)


@router.get("/rates/latest")
async def rates_latest(
    base: str = Query("CNY"),
    quote: str = Query("MYR"),
):
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="not implemented yet"
    )


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
