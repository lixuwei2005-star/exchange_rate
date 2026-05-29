"""Public /api/config + admin validation for the homepage headline channel.

`display.headline_channel` picks which channel's rate the homepage hero shows.
The public endpoint exposes it (default 'midmarket'); the admin settings PUT
guards it so it can only point at an existing, active channel.
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
from httpx import ASGITransport

from app.auth import hash_password
from app.main import app
from app.models.admin_user import AdminUser
from app.models.channel import Channel
from app.services.settings import set_setting


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_config_defaults_to_midmarket_when_unset(session):
    async with _client() as client:
        resp = await client.get("/api/config")
    assert resp.status_code == 200
    assert resp.json() == {"headline_channel": "midmarket"}


@pytest.mark.asyncio
async def test_config_reflects_stored_setting(session):
    await set_setting(session, "display.headline_channel", "wise")
    await session.commit()
    async with _client() as client:
        resp = await client.get("/api/config")
    assert resp.status_code == 200
    assert resp.json()["headline_channel"] == "wise"


async def _login(client: httpx.AsyncClient) -> None:
    r = await client.post("/api/admin/login", json={"username": "admin", "password": "test"})
    assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_admin_put_headline_accepts_active_channel(session):
    session.add(
        AdminUser(
            username="admin",
            password_hash=hash_password("test"),
            created_at=datetime.now(UTC),
        )
    )
    session.add(Channel(code="wise", name_en="Wise", name_zh="Wise", active=True))
    await session.commit()

    async with _client() as client:
        await _login(client)
        r = await client.put("/api/admin/settings/display.headline_channel", json={"value": "wise"})
    assert r.status_code == 200, r.text
    assert r.json()["value"] == "wise"


@pytest.mark.asyncio
async def test_admin_put_headline_rejects_inactive_channel(session):
    session.add(
        AdminUser(
            username="admin",
            password_hash=hash_password("test"),
            created_at=datetime.now(UTC),
        )
    )
    session.add(Channel(code="boc", name_en="BOC", name_zh="中国银行", active=False))
    await session.commit()

    async with _client() as client:
        await _login(client)
        r = await client.put("/api/admin/settings/display.headline_channel", json={"value": "boc"})
    assert r.status_code == 400
    assert "inactive" in r.json()["detail"]


@pytest.mark.asyncio
async def test_admin_put_headline_rejects_unknown_channel(session):
    session.add(
        AdminUser(
            username="admin",
            password_hash=hash_password("test"),
            created_at=datetime.now(UTC),
        )
    )
    await session.commit()

    async with _client() as client:
        await _login(client)
        r = await client.put("/api/admin/settings/display.headline_channel", json={"value": "nope"})
    assert r.status_code == 400
    assert "unknown channel" in r.json()["detail"]
