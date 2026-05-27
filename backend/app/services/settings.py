from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crypto import decrypt, encrypt, is_sensitive
from app.models.setting import Setting

MASKED = "***"


async def get_setting(session: AsyncSession, key: str, default: str = "") -> str:
    """Return the plaintext value of a setting (auto-decrypts if encrypted).
    Never log the return value for sensitive keys."""
    row = await session.get(Setting, key)
    if row is None:
        return default
    if row.is_encrypted:
        return decrypt(row.value)
    return row.value


async def set_setting(session: AsyncSession, key: str, value: str) -> Setting:
    """Write a setting. Sensitive keys are Fernet-encrypted before storage."""
    encrypted = is_sensitive(key)
    stored_value = encrypt(value) if encrypted else value

    row = await session.get(Setting, key)
    now = datetime.now(UTC)
    if row is None:
        row = Setting(key=key, value=stored_value, is_encrypted=encrypted, updated_at=now)
        session.add(row)
    else:
        row.value = stored_value
        row.is_encrypted = encrypted
        row.updated_at = now
    await session.flush()
    return row


async def list_settings_masked(session: AsyncSession) -> list[Setting]:
    """Return all settings with sensitive values replaced by '***'."""
    result = await session.execute(select(Setting).order_by(Setting.key))
    rows = list(result.scalars().all())
    for r in rows:
        if r.is_encrypted:
            r.value = MASKED  # in-place; the row is detached after the request
    return rows


async def ensure_default(session: AsyncSession, key: str, default: str) -> None:
    """Insert key=default only if the row does not exist. No-op if already set."""
    row = await session.get(Setting, key)
    if row is None:
        await set_setting(session, key, default)
