"""Pytest config: set required env vars before app modules are imported, and
provide an in-memory SQLite for tests that touch the DB."""

from __future__ import annotations

import os

# Must be set before any app.* import: pydantic-settings reads them at import.
os.environ.setdefault("FERNET_KEY", "jXV6ArgMcNyfMYx2bl6w2BQZtNsraEP2W0hs0HAVB6I=")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-padded-to-be-long-enough-for-hs256")
os.environ.setdefault("ENV", "dev")
os.environ.setdefault("ADMIN_USERNAME", "admin")
os.environ.setdefault("ADMIN_PASSWORD", "test")
# In-memory SQLite so tests don't touch the dev DB.
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

import pytest_asyncio  # noqa: E402

from app.db import Base, SessionLocal, engine  # noqa: E402


@pytest_asyncio.fixture(autouse=True)
async def _prepare_db():
    """Create + drop all tables for every test. Cheap with in-memory SQLite."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture()
async def session():
    async with SessionLocal() as s:
        yield s
