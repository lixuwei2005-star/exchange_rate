from __future__ import annotations

import pytest

from app.crypto import decrypt, encrypt, is_sensitive
from app.services.settings import get_setting, list_settings_masked, set_setting


def test_is_sensitive():
    assert is_sensitive("ai.api_key")
    assert is_sensitive("openai.secret")
    assert is_sensitive("admin.password")
    assert not is_sensitive("ai.model")
    assert not is_sensitive("ai.enabled")


def test_encrypt_roundtrip():
    plaintext = "sk-very-secret-token-1234"
    ct = encrypt(plaintext)
    assert ct != plaintext
    assert decrypt(ct) == plaintext


def test_encrypt_empty_is_empty():
    assert encrypt("") == ""
    assert decrypt("") == ""


@pytest.mark.asyncio
async def test_set_get_setting_roundtrip(session):
    await set_setting(session, "ai.model", "gpt-4o-mini")
    assert await get_setting(session, "ai.model") == "gpt-4o-mini"


@pytest.mark.asyncio
async def test_sensitive_setting_is_encrypted_at_rest(session):
    raw = "sk-abcdef-token"
    row = await set_setting(session, "ai.api_key", raw)
    assert row.is_encrypted is True
    assert row.value != raw  # stored ciphertext
    # But get_setting transparently decrypts
    assert await get_setting(session, "ai.api_key") == raw


@pytest.mark.asyncio
async def test_list_masks_sensitive(session):
    await set_setting(session, "ai.api_key", "sk-aaaa")
    await set_setting(session, "ai.model", "gpt-4o-mini")
    rows = await list_settings_masked(session)
    by_key = {r.key: r for r in rows}
    assert by_key["ai.api_key"].value == "***"
    assert by_key["ai.model"].value == "gpt-4o-mini"
