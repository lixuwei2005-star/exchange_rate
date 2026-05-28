from __future__ import annotations

import time
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import (
    clear_admin_cookie,
    current_admin,
    encode_jwt,
    set_admin_cookie,
    verify_password,
)
from app.db import get_session
from app.models.admin_user import AdminUser
from app.models.ai_summary import AISummary
from app.models.channel import Channel
from app.models.scrape_log import ScrapeLog
from app.models.setting import Setting
from app.scheduler import schedule_channel, unschedule_channel
from app.schemas.admin import (
    AITestResult,
    ChannelOut,
    ChannelPatch,
    LoginRequest,
    MeResponse,
    ScrapeLogOut,
    SettingOut,
    SettingPut,
    SummaryAdminOut,
)
from app.scrapers import ALL_SCRAPERS
from app.services.llm_client import get_client
from app.services.scraping import run_scraper
from app.services.settings import MASKED, get_setting, list_settings_masked, set_setting
from app.services.summary import regenerate as regenerate_summary

router = APIRouter(prefix="/api/admin", tags=["admin"])


# -- auth -----------------------------------------------------------------


@router.post("/login")
async def login(
    body: LoginRequest,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    user = (
        await session.execute(select(AdminUser).where(AdminUser.username == body.username))
    ).scalar_one_or_none()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid credentials")
    token = encode_jwt(username=user.username)
    set_admin_cookie(response, token)
    return {"ok": True, "username": user.username}


@router.post("/logout")
async def logout(response: Response) -> dict:
    clear_admin_cookie(response)
    return {"ok": True}


@router.get("/me", response_model=MeResponse)
async def me(user: Annotated[AdminUser, Depends(current_admin)]) -> MeResponse:
    return MeResponse(username=user.username)


# -- channels -------------------------------------------------------------


@router.get("/channels", response_model=list[ChannelOut])
async def list_channels(
    _user: Annotated[AdminUser, Depends(current_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[ChannelOut]:
    rows = (await session.execute(select(Channel).order_by(Channel.code))).scalars().all()
    return [ChannelOut.model_validate(r) for r in rows]


@router.patch("/channels/{code}", response_model=ChannelOut)
async def patch_channel(
    code: str,
    body: ChannelPatch,
    _user: Annotated[AdminUser, Depends(current_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ChannelOut:
    ch = await session.get(Channel, code)
    if ch is None:
        raise HTTPException(status_code=404, detail=f"unknown channel: {code}")
    was_active = ch.active
    schedule_changed = False
    if body.active is not None:
        ch.active = body.active
    if body.name_en is not None:
        ch.name_en = body.name_en
    if body.name_zh is not None:
        ch.name_zh = body.name_zh
    if body.source_url is not None:
        ch.source_url = body.source_url
    if body.schedule_kind is not None:
        ch.schedule_kind = body.schedule_kind
        schedule_changed = True
    if body.interval_minutes is not None:
        ch.interval_minutes = body.interval_minutes
        schedule_changed = True
    if body.daily_time_cn is not None:
        ch.daily_time_cn = body.daily_time_cn
        schedule_changed = True
    await session.commit()
    await session.refresh(ch)

    activation_changed = body.active is not None and body.active != was_active
    if activation_changed:
        if ch.active and code in ALL_SCRAPERS:
            await schedule_channel(code)
        else:
            unschedule_channel(code)
    elif schedule_changed and ch.active and code in ALL_SCRAPERS:
        # Same channel, new cadence — re-register the job in place.
        await schedule_channel(code)
    return ChannelOut.model_validate(ch)


@router.post("/channels/{code}/scrape-now")
async def scrape_now(
    code: str,
    _user: Annotated[AdminUser, Depends(current_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
    base: str = "CNY",
    quote: str = "MYR",
) -> dict:
    if code not in ALL_SCRAPERS:
        raise HTTPException(status_code=404, detail=f"unknown channel: {code}")
    channel = await session.get(Channel, code)
    if channel is None:
        raise HTTPException(status_code=404, detail=f"channel '{code}' not in DB")
    snap = await run_scraper(code, base=base, quote=quote)
    if snap is None:
        raise HTTPException(
            status_code=502,
            detail="scrape failed; see channel.last_error_msg and /api/admin/logs",
        )
    return {
        "ok": True,
        "channel": code,
        "rate": str(snap.rate),
        "fetched_at": snap.fetched_at.isoformat(),
    }


# -- settings -------------------------------------------------------------


@router.get("/settings", response_model=list[SettingOut])
async def list_settings(
    _user: Annotated[AdminUser, Depends(current_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[SettingOut]:
    rows = await list_settings_masked(session)
    return [
        SettingOut(key=r.key, value=r.value, is_encrypted=r.is_encrypted, updated_at=r.updated_at)
        for r in rows
    ]


@router.put("/settings/{key}", response_model=SettingOut)
async def put_setting_endpoint(
    key: str,
    body: SettingPut,
    _user: Annotated[AdminUser, Depends(current_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SettingOut:
    # Per CLAUDE.md §11: empty string or "***" means "user didn't change it"
    # — leave the stored value alone instead of clearing the api key.
    if body.value in ("", MASKED):
        existing = await session.get(Setting, key)
        if existing is None:
            raise HTTPException(status_code=404, detail=f"unknown setting key: {key}")
        return SettingOut(
            key=existing.key,
            value=MASKED if existing.is_encrypted else existing.value,
            is_encrypted=existing.is_encrypted,
            updated_at=existing.updated_at,
        )
    row = await set_setting(session, key, body.value)
    await session.commit()
    await session.refresh(row)
    return SettingOut(
        key=row.key,
        value=MASKED if row.is_encrypted else row.value,
        is_encrypted=row.is_encrypted,
        updated_at=row.updated_at,
    )


# -- AI -------------------------------------------------------------------


@router.post("/ai/test", response_model=AITestResult)
async def ai_test(
    _user: Annotated[AdminUser, Depends(current_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AITestResult:
    """Round-trip a 1-token ping against the configured LLM."""
    try:
        client = await get_client(session)
        model = await get_setting(session, "ai.model", "gpt-4o-mini")
        t0 = time.perf_counter()
        resp = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=1,
        )
        latency_ms = int((time.perf_counter() - t0) * 1000)
        used = resp.model if resp.model else model
        return AITestResult(ok=True, latency_ms=latency_ms, model_used=used)
    except Exception as exc:
        return AITestResult(ok=False, error=str(exc)[:500])


@router.get("/summaries", response_model=list[SummaryAdminOut])
async def list_summaries(
    _user: Annotated[AdminUser, Depends(current_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: int = Query(20, ge=1, le=100),
) -> list[SummaryAdminOut]:
    rows = (
        (
            await session.execute(
                select(AISummary).order_by(desc(AISummary.generated_at)).limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return [SummaryAdminOut.model_validate(r) for r in rows]


@router.post("/summaries/regenerate")
async def regenerate_summary_endpoint(
    _user: Annotated[AdminUser, Depends(current_admin)],
    base: str = "CNY",
    quote: str = "MYR",
) -> dict:
    row = await regenerate_summary(base=base, quote=quote)
    if row is None:
        raise HTTPException(
            status_code=502,
            detail="summary regeneration produced no output; see /api/admin/logs",
        )
    return {
        "ok": True,
        "summary": row.summary_zh,
        "model_used": row.model_used,
        "generated_at": row.generated_at.isoformat(),
    }


# -- logs -----------------------------------------------------------------


@router.get("/logs", response_model=list[ScrapeLogOut])
async def list_logs(
    _user: Annotated[AdminUser, Depends(current_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: int = Query(200, ge=1, le=1000),
    level: str | None = Query(None),
) -> list[ScrapeLogOut]:
    q = select(ScrapeLog).order_by(desc(ScrapeLog.created_at)).limit(limit)
    if level:
        q = q.where(ScrapeLog.level == level)
    rows = (await session.execute(q)).scalars().all()
    return [ScrapeLogOut.model_validate(r) for r in rows]
