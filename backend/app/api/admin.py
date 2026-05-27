from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
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
from app.models.channel import Channel
from app.schemas.admin import LoginRequest, MeResponse
from app.scrapers import ALL_SCRAPERS
from app.services.scraping import run_scraper

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


# -- everything else: 501 stubs until later phases -----------------------


def _not_impl():
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="not implemented yet")


@router.get("/channels")
async def list_channels(user: Annotated[AdminUser, Depends(current_admin)]):
    _not_impl()


@router.patch("/channels/{code}")
async def patch_channel(code: str, user: Annotated[AdminUser, Depends(current_admin)]):
    _not_impl()


@router.post("/channels/{code}/scrape-now")
async def scrape_now(
    code: str,
    user: Annotated[AdminUser, Depends(current_admin)],
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
        # The scraper logged the error; surface it to the admin UI as 502.
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


@router.get("/settings")
async def list_settings(user: Annotated[AdminUser, Depends(current_admin)]):
    _not_impl()


@router.put("/settings/{key}")
async def put_setting(key: str, user: Annotated[AdminUser, Depends(current_admin)]):
    _not_impl()


@router.post("/ai/test")
async def ai_test(user: Annotated[AdminUser, Depends(current_admin)]):
    _not_impl()


@router.get("/summaries")
async def list_summaries(user: Annotated[AdminUser, Depends(current_admin)]):
    _not_impl()


@router.post("/summaries/regenerate")
async def regenerate_summary(user: Annotated[AdminUser, Depends(current_admin)]):
    _not_impl()


@router.get("/logs")
async def list_logs(user: Annotated[AdminUser, Depends(current_admin)]):
    _not_impl()
