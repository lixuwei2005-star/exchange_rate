from __future__ import annotations

import pytest

from app.auth import decode_jwt, encode_jwt, hash_password, verify_password


def test_password_roundtrip():
    h = hash_password("secret-pw-123")
    assert h != "secret-pw-123"
    assert verify_password("secret-pw-123", h)
    assert not verify_password("wrong", h)


def test_jwt_roundtrip():
    token = encode_jwt(username="alice")
    decoded = decode_jwt(token)
    assert decoded["sub"] == "alice"
    assert "exp" in decoded
    assert "iat" in decoded


def test_jwt_rejects_garbage():
    import jwt as _jwt

    with pytest.raises(_jwt.InvalidTokenError):
        decode_jwt("not-a-token")
