from __future__ import annotations

import re
from functools import lru_cache

from cryptography.fernet import Fernet

from app.config import get_settings

# Keys matching these patterns get auto-encrypted by services/settings.py
SENSITIVE_KEY_PATTERN = re.compile(r"\.(api_key|secret|password)$")


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    key = get_settings().fernet_key.encode()
    return Fernet(key)


def is_sensitive(key: str) -> bool:
    """Whether a settings key name should have its value encrypted at rest."""
    return bool(SENSITIVE_KEY_PATTERN.search(key))


def encrypt(plaintext: str) -> str:
    if plaintext == "":
        # Storing empty as empty keeps the "not set" semantics clear.
        return ""
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    if ciphertext == "":
        return ""
    return _fernet().decrypt(ciphertext.encode()).decode()
